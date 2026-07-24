from dataclasses import dataclass

from smartadvisor_automation.probe import selector_match_strategy


@dataclass
class FakeElementInfo:
    automation_id: str = ""
    control_id: int | None = None


def test_named_automation_id_matches_exactly() -> None:
    info = FakeElementInfo(automation_id="cboClient", control_id=10)

    assert selector_match_strategy(info, "cboClient") == "automation_id"


def test_numeric_automation_id_can_match_control_id() -> None:
    info = FakeElementInfo(automation_id="", control_id=263892)

    assert selector_match_strategy(info, "263892") == "control_id"


def test_selector_does_not_match_partial_values() -> None:
    info = FakeElementInfo(automation_id="cboClientOther", control_id=263892)

    assert selector_match_strategy(info, "cboClient") is None

