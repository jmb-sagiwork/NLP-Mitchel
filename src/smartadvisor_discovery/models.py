from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

Action = Literal["click", "clear", "input", "extract", "close"]


@dataclass(frozen=True, slots=True)
class ControlSpec:
    """A non-sensitive selector definition for one workflow control."""

    step: str
    automation_id: str
    label: str
    action: Action
    common_to_all_cases: bool = False


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Sanitized outcome of locating one control with one backend."""

    backend: str
    step: str
    automation_id: str
    label: str
    intended_action: Action
    status: str
    match_strategy: str | None = None
    match_count: int = 0
    control_type: str | None = None
    class_name: str | None = None
    visible: bool | None = None
    enabled: bool | None = None
    rectangle: dict[str, int] | None = None
    error_code: str | None = None

    def to_public_dict(self) -> dict[str, object]:
        """Return selector metadata without control text or field values."""

        return asdict(self)

