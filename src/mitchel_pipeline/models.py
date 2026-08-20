from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True, slots=True)
class ExtractedEmail:
    """One CXone email after reply-chain cleanup."""

    message_id: str
    subject: str
    body: str
    saved_path: Path


@dataclass(frozen=True, slots=True)
class SmartAdvisorJob:
    """A single, safely paired SmartAdvisor lookup."""

    claim_id: str
    dos_from: str
    expected_amount: str
    source_message_id: str

    @property
    def deduplication_key(self) -> tuple[str, str, str]:
        return (
            self.claim_id.casefold(),
            self.dos_from,
            self.expected_amount.replace("$", "").replace(",", "").strip(),
        )

    def to_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SmartAdvisorJob:
        return cls(
            claim_id=str(value["claim_id"]),
            dos_from=str(value["dos_from"]),
            expected_amount=str(value["expected_amount"]),
            source_message_id=str(value.get("source_message_id", "")),
        )


EventKind = Literal["status", "progress", "summary", "error", "complete"]


@dataclass(frozen=True, slots=True)
class PipelineEvent:
    kind: EventKind
    message: str
    progress: float
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RunSummary:
    extracted: int = 0
    classified: int = 0
    skipped: int = 0
    jobs_created: int = 0
    jobs_completed: int = 0
    nlp_errors: int = 0
    smartadvisor_errors: int = 0

    def display(self) -> str:
        return (
            f"Emails {self.extracted}  |  Jobs {self.jobs_completed}/{self.jobs_created}"
            f"  |  Skipped {self.skipped}"
        )

    def to_dict(self) -> dict[str, int]:
        return asdict(self)
