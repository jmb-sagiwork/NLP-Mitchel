"""Normalization, thread splitting, and signature detection.

The classifier reads the newest message. Quoted history is kept as a separate
segment so a required field can be recovered from it when the newest message
omits it, without letting stale identifiers drive the classification.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .types import Segment

# "On Mon, Mar 14, 2026 at 9:02 AM Someone wrote:" and friends.
_REPLY_MARKERS = [
    re.compile(r"^\s*On .{0,120}\bwrote:\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*-{2,}\s*Forwarded message\s*-{2,}\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*_{5,}\s*$", re.MULTILINE),
    re.compile(r"^\s*From:\s*.+$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*Sent:\s*.+$", re.IGNORECASE | re.MULTILINE),
]

_SIGNATURE_MARKERS = [
    re.compile(r"^\s*--\s*$", re.MULTILINE),
    re.compile(r"^\s*(?:Thanks|Thank you|Regards|Best regards|Sincerely|Kind regards)[,!.]?\s*$",
               re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*Sent from my \w+", re.IGNORECASE | re.MULTILINE),
    re.compile(r"CONFIDENTIALITY NOTICE", re.IGNORECASE),
    re.compile(r"This (?:e-?mail|message) (?:and any attachments )?(?:is|are) confidential",
               re.IGNORECASE),
]

_QUOTE_PREFIX = re.compile(r"^\s*>+\s?", re.MULTILINE)
_TRANSPORT_HEADER = re.compile(
    r"^(From|Sent|To|Subject):[ \t]*(.*)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TextSegment:
    kind: str          # a Segment value
    text: str
    offset: int        # start offset within the normalized full text


@dataclass(frozen=True)
class PreparedText:
    """Everything downstream layers read."""

    full: str                       # normalized subject + body, offsets refer to this
    subject: str
    body: str
    segments: tuple[TextSegment, ...]

    def segment(self, kind: str) -> TextSegment | None:
        for s in self.segments:
            if s.kind == kind:
                return s
        return None

    @property
    def classify_text(self) -> str:
        """What the embedding and rule layers score. Newest message only."""
        parts = [s.text for s in self.segments
                 if s.kind in (Segment.SUBJECT.value, Segment.NEWEST_BODY.value)]
        return "\n".join(p for p in parts if p.strip())


def normalize(text: str) -> str:
    """NFKC, de-tab, unwrap hard wraps, collapse runs of blank lines.

    Length-preserving where it can be, because field spans point into the result.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\t", " ")
    text = text.replace(" ", " ")
    # Collapse 3+ newlines to 2. Not length-preserving, so it happens before
    # any span is computed.
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Trim trailing spaces per line.
    text = re.sub(r"[ ]+$", "", text, flags=re.MULTILINE)
    return text.strip()


def separate_transport_headers(body: str, subject: str = "") -> tuple[str, str]:
    """Move a pasted mail header's Subject into the subject and remove headers.

    Outlook/NICE copies can begin with a contiguous From/Sent/To/Subject block.
    That block is metadata for the newest message, not quoted history. Requiring
    at least two recognized headers avoids stripping ordinary prose that happens
    to begin with a single ``From:`` or ``Subject:`` line.
    """

    body_n = normalize(body)
    subject_n = normalize(subject)
    lines = body_n.splitlines()
    headers: dict[str, str] = {}
    index = 0
    while index < len(lines):
        match = _TRANSPORT_HEADER.fullmatch(lines[index])
        if match is None:
            break
        headers[match.group(1).casefold()] = match.group(2).strip()
        index += 1

    if len(headers) < 2 or "subject" not in headers:
        return subject_n, body_n

    while index < len(lines) and not lines[index].strip():
        index += 1
    clean_body = normalize("\n".join(lines[index:]))
    clean_subject = subject_n or normalize(headers["subject"])
    return clean_subject, clean_body


def _first_reply_marker(text: str) -> int | None:
    positions = [m.start() for pat in _REPLY_MARKERS for m in pat.finditer(text)]
    # Ignore a marker at the very top: that is a forwarded header, not history.
    positions = [p for p in positions if p > 0]
    return min(positions) if positions else None


def _signature_start(text: str) -> int | None:
    positions = [m.start() for pat in _SIGNATURE_MARKERS for m in pat.finditer(text)]
    if not positions:
        return None
    start = min(positions)
    # Only treat it as a signature if it is in the back half; a "Thanks," on
    # line 1 is a greeting, not a sign-off.
    return start if start > len(text) * 0.35 else None


def prepare(body: str, subject: str = "") -> PreparedText:
    """Split raw input into ordered segments with stable offsets."""
    subject_n, body_n = separate_transport_headers(body, subject)

    if subject_n:
        full = f"{subject_n}\n{body_n}"
        body_offset = len(subject_n) + 1
    else:
        full = body_n
        body_offset = 0

    segments: list[TextSegment] = []
    if subject_n:
        segments.append(TextSegment(Segment.SUBJECT.value, subject_n, 0))

    cut = _first_reply_marker(body_n)
    newest = body_n if cut is None else body_n[:cut].rstrip()
    history = "" if cut is None else body_n[cut:]

    sig_at = _signature_start(newest)
    if sig_at is not None:
        signature = newest[sig_at:]
        newest = newest[:sig_at].rstrip()
    else:
        signature = ""

    segments.append(TextSegment(Segment.NEWEST_BODY.value, newest, body_offset))
    if signature:
        segments.append(
            TextSegment(Segment.SIGNATURE.value, signature, body_offset + (sig_at or 0))
        )
    if history:
        # Strip ">" quote prefixes for matching, but keep the offset anchored.
        segments.append(
            TextSegment(Segment.QUOTED_HISTORY.value, _QUOTE_PREFIX.sub("", history),
                        body_offset + (cut or 0))
        )

    return PreparedText(full=full, subject=subject_n, body=body_n, segments=tuple(segments))
