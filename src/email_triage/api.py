"""The plug-and-play surface.

A host system does exactly this:

    from email_triage import classify_email
    result = classify_email(body, subject)
    if result.needs_review:
        route_to_human(result.to_dict())

Two strings in, one JSON-serialisable result out. Where those strings came from
- a mailbox, a ticket queue, a form post - is the host's problem, not this
package's. Nothing else here is a stable contract.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence

from .engine import TriageEngine, get_default_engine
from .types import TriageResult


def classify_email(
    body: str,
    subject: str = "",
    *,
    message_key: str | None = None,
    engine: TriageEngine | None = None,
) -> TriageResult:
    """Classify one email and extract the fields its concern requires.

    `body` and `subject` are the whole input. `subject` may be passed
    positionally or by keyword; both are plain text, and HTML mail should be
    flattened by the caller before it gets here.

    `message_key` is an opaque caller-supplied id echoed back on the result. It
    is never logged raw. `engine` lets a long-running host reuse one loaded
    model instead of paying for the default engine's lazy construction.
    """
    return (engine or get_default_engine()).classify(
        body, subject=subject, message_key=message_key
    )


def classify_emails(
    items: Iterable[Sequence[str] | Mapping[str, str]],
    *,
    engine: TriageEngine | None = None,
) -> list[TriageResult]:
    """Classify many, reusing one engine.

    Each item is `(body,)`, `(body, subject)`, or a mapping with `body` and
    optional `subject` / `message_key` keys - the mapping form is there because
    a host queue usually already holds dicts.
    """
    eng = engine or get_default_engine()
    out: list[TriageResult] = []
    for item in items:
        if isinstance(item, Mapping):
            out.append(
                eng.classify(
                    item["body"],
                    subject=item.get("subject", ""),
                    message_key=item.get("message_key"),
                )
            )
        else:
            body = item[0]
            subject = item[1] if len(item) > 1 else ""
            out.append(eng.classify(body, subject=subject))
    return out
