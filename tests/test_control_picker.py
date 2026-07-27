from types import SimpleNamespace

import pytest

from smartadvisor_automation.control_picker import (
    PickerError,
    build_report,
    describe_candidate,
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


def test_build_report_includes_confirmed_and_siblings() -> None:
    a = make_element("A")
    b = make_element("B")

    report = build_report(b, [a, b])

    assert report["schema_version"] == 1
    assert report["privacy"]["read_only"] is True
    assert report["confirmed"]["automation_id"] == "B"
    assert [s["automation_id"] for s in report["siblings"]] == ["A", "B"]
