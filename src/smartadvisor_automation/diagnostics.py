from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class DiagnosticTrace:
    """Redacted step-by-step record of one attach handshake attempt.

    Records counts and outcomes only: no window titles, control text,
    claim data, or field values.
    """

    steps: list[dict[str, object]] = field(default_factory=list)

    def record(
        self,
        stage: str,
        backend: str,
        outcome: str,
        **details: object,
    ) -> None:
        self.steps.append(
            {
                "stage": stage,
                "backend": backend,
                "outcome": outcome,
                **details,
            }
        )

    def to_report(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "privacy": {
                "includes_window_titles": False,
                "includes_field_values": False,
            },
            "steps": self.steps,
        }
