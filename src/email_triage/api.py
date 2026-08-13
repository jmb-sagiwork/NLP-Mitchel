"""The plug-and-play surface.

A host system does exactly this:

    from email_triage import classify_email
    result = classify_email(body, subject=subj)
    if result.needs_review:
        route_to_human(result.to_dict())

Nothing else in this package is a stable contract.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from .engine import TriageEngine, get_default_engine
from .types import TriageResult


def classify_email(
    body: str,
    *,
    subject: str = "",
    message_key: str | None = None,
    engine: TriageEngine | None = None,
) -> TriageResult:
    """Classify one email and extract the fields its concern requires.

    `message_key` is an opaque caller-supplied id echoed back on the result. It
    is never logged raw.
    """
    return (engine or get_default_engine()).classify(
        body, subject=subject, message_key=message_key
    )


def classify_emails(
    items: Iterable[Sequence[str]],
    *,
    engine: TriageEngine | None = None,
) -> list[TriageResult]:
    """Classify many. Each item is (body,) or (body, subject)."""
    eng = engine or get_default_engine()
    out: list[TriageResult] = []
    for item in items:
        body = item[0]
        subject = item[1] if len(item) > 1 else ""
        out.append(eng.classify(body, subject=subject))
    return out
