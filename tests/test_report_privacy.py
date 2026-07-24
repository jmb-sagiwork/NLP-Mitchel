from collections.abc import Mapping

from smartadvisor_automation.object_extractor import (
    extract_smartadvisor_objects,
)
from smartadvisor_automation.probe import scan_controls

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


def test_report_schema_does_not_contain_sensitive_value_keys(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "smartadvisor_automation.probe.probe_backend",
        lambda backend: {
            "backend": backend,
            "window_status": "not_found",
            "error_code": None,
            "controls": [],
        },
    )

    report = scan_controls()

    assert FORBIDDEN_KEYS.isdisjoint(_all_keys(report))
    assert report["privacy"]["includes_control_text"] is False
    assert report["privacy"]["includes_field_values"] is False


def test_object_report_schema_does_not_contain_sensitive_value_keys(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "smartadvisor_automation.object_extractor."
        "_native_smartadvisor_handles",
        lambda: [],
    )
    monkeypatch.setattr(
        "smartadvisor_automation.object_extractor."
        "_preferred_native_handle",
        lambda _handles: None,
    )

    report = extract_smartadvisor_objects()

    assert FORBIDDEN_KEYS.isdisjoint(_all_keys(report))
    assert report["privacy"]["includes_field_values"] is False
    assert report["privacy"]["includes_unknown_names"] is False

