from types import SimpleNamespace

import pytest

from smartadvisor_automation.control_picker import (
    MAX_LABEL_LENGTH,
    PickerError,
    build_entry,
    build_recording_report,
    describe_candidate,
    sanitize_label,
    walk,
)


def make_element(automation_id: str, children: list | None = None):
    child_list = children if children is not None else []
    info = SimpleNamespace(
        automation_id=automation_id,
        name="",
        control_type="Button",
        class_name="WindowsForms10.Window.8.app.0.dynamic_ad1",
        framework_id="WinForm",
        handle=1,
        process_id=1234,
        runtime_id=[42, 1],
        visible=True,
        enabled=True,
        rectangle=None,
    )
    return SimpleNamespace(element_info=info, children=lambda: child_list)


def drive(gen, answers):
    """Send each answer in turn, returning the StopIteration value."""

    candidate, _siblings = next(gen)
    for answer in answers:
        try:
            candidate, _siblings = gen.send(answer)
        except StopIteration as stop:
            return stop.value
    raise AssertionError("walk did not stop - ran out of answers")


def test_walk_advances_through_siblings_on_no() -> None:
    a = make_element("A")
    b = make_element("B")
    c = make_element("C")
    root = make_element("root", children=[a, b, c])

    result = drive(walk(root), ["no", "no", "final"])

    assert result[0] is c
    assert result[1] == [a, b, c]


def test_walk_descends_into_children_on_yes() -> None:
    grandchild_1 = make_element("GC1")
    grandchild_2 = make_element("GC2")
    child_a = make_element("A")
    child_b = make_element("B", children=[grandchild_1, grandchild_2])
    root = make_element("root", children=[child_a, child_b])

    result = drive(walk(root), ["no", "yes", "final"])

    assert result[0] is grandchild_1
    assert result[1] == [grandchild_1, grandchild_2]


def test_walk_raises_when_level_has_no_children() -> None:
    root = make_element("root", children=[])

    gen = walk(root)
    with pytest.raises(PickerError) as captured:
        next(gen)

    assert captured.value.code == "no_children_at_this_level"


def test_walk_raises_when_every_sibling_answered_no() -> None:
    a = make_element("A")
    b = make_element("B")
    root = make_element("root", children=[a, b])

    gen = walk(root)
    with pytest.raises(PickerError) as captured:
        drive(gen, ["no", "no"])

    assert captured.value.code == "no_match_at_this_level"


def test_describe_candidate_redacts_name_and_keeps_automation_id() -> None:
    element = make_element("_Toolbar1_Button2")
    element.element_info.name = "some customer-adjacent text"

    described = describe_candidate(element)

    assert described["automation_id"] == "_Toolbar1_Button2"
    assert described["name"] == {"status": "redacted"}


def test_walk_returns_the_path_it_descended_through() -> None:
    target = make_element("target")
    inner = make_element("inner", children=[target])
    outer = make_element("outer", children=[inner])
    other = make_element("other")
    root = make_element("root", children=[other, outer])

    confirmed, _siblings, path = drive(
        walk(root), ["no", "yes", "yes", "final"]
    )

    assert confirmed is target
    assert path == [root, outer, inner]


def test_build_entry_records_the_full_path_to_the_control() -> None:
    target = make_element("_Toolbar1_Button2")
    inner = make_element("Toolbar1")
    root = make_element("frmMain")

    entry = build_entry(
        target,
        [target],
        [root, inner],
        label="open bill launcher",
        index=3,
    )

    assert entry["entry_index"] == 3
    assert entry["label"] == "open bill launcher"
    assert entry["path_depth"] == 2
    assert [node["automation_id"] for node in entry["path"]] == [
        "frmMain",
        "Toolbar1",
    ]
    assert [node["depth"] for node in entry["path"]] == [0, 1]
    assert [node["parent_id"] for node in entry["path"]] == [None, "path_0"]
    assert entry["confirmed"]["automation_id"] == "_Toolbar1_Button2"
    assert entry["confirmed"]["parent_id"] == "path_1"
    assert entry["confirmed"]["depth"] == 2


def test_build_entry_redacts_names_along_the_whole_path() -> None:
    target = make_element("target")
    root = make_element("frmMain")
    root.element_info.name = "customer-adjacent parent text"
    target.element_info.name = "customer-adjacent target text"

    entry = build_entry(target, [target], [root])

    assert entry["path"][0]["name"] == {"status": "redacted"}
    assert entry["confirmed"]["name"] == {"status": "redacted"}


def test_build_recording_report_holds_every_entry() -> None:
    first = build_entry(make_element("A"), [], [], label="one", index=1)
    second = build_entry(make_element("B"), [], [], label="two", index=2)

    report = build_recording_report([first, second])

    assert report["schema_version"] == 2
    assert report["privacy"]["read_only"] is True
    assert report["entry_count"] == 2
    assert [e["label"] for e in report["entries"]] == ["one", "two"]
    assert [
        e["confirmed"]["automation_id"] for e in report["entries"]
    ] == ["A", "B"]


def test_sanitize_label_collapses_whitespace_and_caps_length() -> None:
    assert sanitize_label("  open   bill  launcher \n") == (
        "open bill launcher"
    )
    assert sanitize_label(None) == ""
    assert len(sanitize_label("x" * 200)) == MAX_LABEL_LENGTH
