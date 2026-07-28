from collections.abc import Mapping
from types import SimpleNamespace

from smartadvisor_automation.action_recorder import (
    ActionRecorder,
    ElementRef,
    ResolvedTarget,
    build_action_report,
)
from smartadvisor_automation.input_hooks import chord_keys, is_character_key

FORBIDDEN_KEYS = {
    "claim_id",
    "control_text",
    "credentials",
    "date_of_service",
    "field_value",
    "patient_account",
    "window_text",
    "window_title",
}


def make_ref(
    automation_id: str,
    *,
    control_type: str = "Button",
    name: str = "",
    process_id: int = 1234,
):
    info = SimpleNamespace(
        automation_id=automation_id,
        name=name,
        control_type=control_type,
        class_name="WindowsForms10.Window.8.app.0.dynamic_ad1",
        framework_id="WinForm",
        handle=1,
        process_id=process_id,
        runtime_id=[42, 1],
        visible=True,
        enabled=True,
        rectangle=None,
    )
    return ElementRef(info)


def make_target(
    automation_id: str,
    *,
    window_id: str = "frmMain",
    chain_ids: tuple[str, ...] = ("frmMain",),
    match_count: int | None = 1,
    control_type: str = "Button",
    process_id: int = 1234,
    name: str = "",
):
    chain = [
        make_ref(node_id, control_type="Window", process_id=process_id)
        for node_id in chain_ids
    ]
    return ResolvedTarget(
        element=make_ref(
            automation_id,
            control_type=control_type,
            process_id=process_id,
            name=name,
        ),
        chain=chain,
        window=make_ref(
            window_id, control_type="Window", process_id=process_id
        ),
        match_count=match_count,
    )


class FakeResolver:
    """Return queued targets for points and focus, in order."""

    def __init__(self, points=None, focus=None) -> None:
        self.points = list(points or [])
        self.focus = list(focus or [])
        self.from_point_calls: list[tuple[int, int]] = []

    def from_point(self, x, y):
        self.from_point_calls.append((x, y))
        return self.points.pop(0) if self.points else None

    def focused(self):
        return self.focus.pop(0) if self.focus else None


def _all_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        keys = {str(key).lower() for key in value}
        for child in value.values():
            keys.update(_all_keys(child))
        return keys
    if isinstance(value, list):
        keys: set[str] = set()
        for child in value:
            keys.update(_all_keys(child))
        return keys
    return set()


def test_click_records_target_path_and_window() -> None:
    resolver = FakeResolver(
        points=[
            make_target(
                "cboClient",
                chain_ids=("frmMain", "frmBillOpen", "Frame1"),
                control_type="ComboBox",
            )
        ]
    )
    recorder = ActionRecorder(resolver, clock=lambda: 0.0)

    recorder.handle_click("left", 400, 300, 10.0)

    step = recorder.steps[0]
    assert resolver.from_point_calls == [(400, 300)]
    assert step["step_index"] == 1
    assert step["action"] == "click"
    assert step["button"] == "left"
    assert step["target"]["automation_id"] == "cboClient"
    assert step["target"]["uniquely_resolvable"] is True
    assert step["target"]["automatable"] is True
    assert [node["automation_id"] for node in step["path"]] == [
        "frmMain",
        "frmBillOpen",
        "Frame1",
    ]
    assert step["window"]["automation_id"] == "frmMain"
    assert step["seconds_since_previous"] is None


def test_typing_collapses_into_one_input_step_without_characters() -> None:
    resolver = FakeResolver(focus=[make_target("txtClaim")])
    recorder = ActionRecorder(resolver, clock=lambda: 0.0)

    recorder.handle_char(1.0)
    recorder.handle_char(1.1)
    recorder.handle_char(1.2)
    recorder.flush_pending()

    assert len(recorder.steps) == 1
    step = recorder.steps[0]
    assert step["action"] == "input"
    assert step["target"]["automation_id"] == "txtClaim"
    assert step["value"] == {
        "status": "not_recorded",
        "source": "run_parameter",
    }
    # Only one focus lookup: characters after the first extend the run.
    assert resolver.focus == []


def test_click_flushes_pending_typing_before_recording() -> None:
    resolver = FakeResolver(
        points=[make_target("cmdOK")], focus=[make_target("txtClaim")]
    )
    recorder = ActionRecorder(resolver, clock=lambda: 0.0)

    recorder.handle_char(1.0)
    recorder.handle_click("left", 10, 20, 2.5)

    assert [step["action"] for step in recorder.steps] == ["input", "click"]
    assert recorder.steps[0]["target"]["automation_id"] == "txtClaim"
    assert recorder.steps[1]["target"]["automation_id"] == "cmdOK"
    assert recorder.steps[1]["seconds_since_previous"] == 1.5


def test_chord_records_accelerator_against_focused_window() -> None:
    resolver = FakeResolver(
        focus=[make_target("frmMain", control_type="Window")]
    )
    recorder = ActionRecorder(resolver, clock=lambda: 0.0)

    recorder.handle_chord("^o", 5.0)

    step = recorder.steps[0]
    assert step["action"] == "key"
    assert step["keys"] == "^o"
    assert step["target"]["automation_id"] == "frmMain"


def test_new_window_is_flagged_when_the_owning_window_changes() -> None:
    resolver = FakeResolver(
        points=[
            make_target("cmdOpen", window_id="frmMain"),
            make_target("cboClient", window_id="frmBillOpen"),
            make_target("cmdOK", window_id="frmBillOpen"),
        ]
    )
    recorder = ActionRecorder(resolver, clock=lambda: 0.0)

    recorder.handle_click("left", 1, 1, 1.0)
    recorder.handle_click("left", 2, 2, 2.0)
    recorder.handle_click("left", 3, 3, 3.0)

    assert [step["opened_new_window"] for step in recorder.steps] == [
        True,
        True,
        False,
    ]


def test_ambiguous_and_unidentifiable_targets_are_flagged() -> None:
    resolver = FakeResolver(
        points=[
            make_target("cboClient", match_count=2),
            make_target("", match_count=None),
        ]
    )
    recorder = ActionRecorder(resolver, clock=lambda: 0.0)

    recorder.handle_click("left", 1, 1, 1.0)
    recorder.handle_click("left", 2, 2, 2.0)
    report = build_action_report(recorder.steps)

    assert report["review"]["steps_not_uniquely_resolvable"] == [1]
    assert report["review"]["steps_without_automation_id"] == [2]


def test_recorder_ignores_its_own_ui() -> None:
    resolver = FakeResolver(
        points=[make_target("btnStop", process_id=999)],
        focus=[make_target("txtLabel", process_id=999)],
    )
    recorder = ActionRecorder(
        resolver, clock=lambda: 0.0, ignore_process_id=999
    )

    recorder.handle_click("left", 1, 1, 1.0)
    recorder.handle_char(2.0)
    recorder.flush_pending()

    assert recorder.steps == []


def test_unresolved_focus_is_skipped_not_recorded() -> None:
    recorder = ActionRecorder(FakeResolver(), clock=lambda: 0.0)

    recorder.handle_char(1.0)
    recorder.flush_pending()

    assert recorder.steps == []
    assert recorder.skipped == [
        {"action": "input", "reason": "focused_control_unresolved"}
    ]


def test_label_and_drop_renumber_steps() -> None:
    resolver = FakeResolver(
        points=[make_target("A"), make_target("B"), make_target("C")]
    )
    recorder = ActionRecorder(resolver, clock=lambda: 0.0)
    for position in range(3):
        recorder.handle_click("left", position, position, float(position))

    recorder.label_step(3, "  the   ok  button ")
    recorder.drop_step(2)

    assert [step["step_index"] for step in recorder.steps] == [1, 2]
    assert [step["target"]["automation_id"] for step in recorder.steps] == [
        "A",
        "C",
    ]
    assert recorder.steps[1]["label"] == "the ok button"


def test_handle_event_dispatches_raw_hook_tuples() -> None:
    resolver = FakeResolver(
        points=[make_target("cmdOK")], focus=[make_target("txtClaim")]
    )
    recorder = ActionRecorder(resolver, clock=lambda: 0.0)

    recorder.handle_event(("char", 1.0))
    recorder.handle_event(("click", "left", 5, 6, 2.0))
    recorder.handle_event(("chord", "{ENTER}", 3.0))

    assert [step["action"] for step in recorder.steps] == [
        "input",
        "click",
        "key",
    ]


def test_report_redacts_names_and_declares_privacy() -> None:
    resolver = FakeResolver(
        points=[
            make_target("cboClient", name="customer-adjacent control text")
        ]
    )
    recorder = ActionRecorder(resolver, clock=lambda: 0.0)
    recorder.handle_click("left", 1, 1, 1.0)

    report = build_action_report(recorder.steps, notes="no bill on file")

    assert report["schema_version"] == 1
    assert report["privacy"]["includes_field_values"] is False
    assert report["privacy"]["includes_typed_characters"] is False
    assert report["notes"] == "no bill on file"
    assert report["step_count"] == 1
    assert report["steps"][0]["target"]["name"] == {"status": "redacted"}


def test_report_contains_no_sensitive_value_keys() -> None:
    resolver = FakeResolver(
        points=[make_target("cboClient")], focus=[make_target("txtClaim")]
    )
    recorder = ActionRecorder(resolver, clock=lambda: 0.0)
    recorder.handle_char(1.0)
    recorder.handle_click("left", 1, 1, 2.0)
    recorder.handle_chord("^o", 3.0)

    report = build_action_report(recorder.steps)

    assert FORBIDDEN_KEYS.isdisjoint(_all_keys(report))


def test_character_keys_never_become_chords() -> None:
    assert is_character_key(0x41) is True
    assert is_character_key(0x39) is True
    assert chord_keys(0x41) is None
    assert chord_keys(0x41, shift=True) is None


def test_keys_with_no_name_and_no_text_are_neither_chord_nor_char() -> None:
    # F13 and media keys must not be mistaken for typing; together these
    # two answers are what makes the hook drop them.
    assert chord_keys(0x7C) is None
    assert is_character_key(0x7C) is False
    assert chord_keys(0x7C, ctrl=True) is None


def test_structural_keys_and_accelerators_map_to_type_keys() -> None:
    assert chord_keys(0x0D) == "{ENTER}"
    assert chord_keys(0x09) == "{TAB}"
    assert chord_keys(0x09, shift=True) == "+{TAB}"
    assert chord_keys(0x4F, ctrl=True) == "^o"
    assert chord_keys(0x46, alt=True) == "%f"
    assert chord_keys(0x74) == "{F5}"
    assert is_character_key(0x0D) is False
