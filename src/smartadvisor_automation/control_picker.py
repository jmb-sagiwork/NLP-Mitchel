from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from smartadvisor_automation.object_extractor import _uia_node
from smartadvisor_automation.probe import find_smartadvisor_window

PICKER_VERSION = "0.2.0"
MAX_LABEL_LENGTH = 60


class PickerError(RuntimeError):
    """A sanitized control-picker failure safe to show in the UI."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def describe_candidate(
    wrapper: Any,
    *,
    node_id: str = "candidate",
    parent_id: str | None = None,
    depth: int = 0,
) -> dict[str, object]:
    """Return the same privacy-safe fields the object extractor records."""

    return _uia_node(
        "uia",
        wrapper.element_info,
        node_id=node_id,
        parent_id=parent_id,
        depth=depth,
    )


def sanitize_label(value: object) -> str:
    """Normalize a user-typed entry label and cap its length.

    Labels are structural nicknames for a control ("open bill launcher"),
    never field values, so they are stored as typed after whitespace
    collapsing and truncation.
    """

    return " ".join(str(value or "").split())[:MAX_LABEL_LENGTH]


def find_start_window() -> Any:
    """Locate the SmartAdvisor main window as the walk's starting parent."""

    window = find_smartadvisor_window("uia")
    if window is None:
        raise PickerError("smartadvisor_window_not_found")
    return window


def child_elements(parent: Any) -> list[Any]:
    """Read one level of direct children, never raising on a bad node."""

    try:
        return list(parent.children())
    except Exception:
        return []


def walk(root: Any):
    """Drive a highlight-and-confirm descent one child at a time.

    A generator so the interactive UI (or a test) drives it step by step:
    prime with `next(gen)`, then repeatedly `gen.send("no" | "yes" |
    "final")` for each yielded `(candidate, siblings)` pair.

    - "no": move to the next sibling at the current level.
    - "yes": the candidate is the right branch but not itself the target;
      descend into its children and restart the sibling walk one level
      deeper.
    - "final": the candidate is the exact control to click; the walk ends
      and `(candidate, siblings, path)` is available as the StopIteration
      value, where `path` is the ancestor chain that was descended through
      to reach it, starting at `root`.

    Raises PickerError if a level has no children, or every sibling at a
    level is answered "no" without ever reaching "yes" or "final".
    """

    parent = root
    path: list[Any] = [root]
    while True:
        siblings = child_elements(parent)
        if not siblings:
            raise PickerError("no_children_at_this_level")

        index = 0
        descended = False
        while index < len(siblings):
            candidate = siblings[index]
            answer = yield candidate, siblings
            if answer == "no":
                index += 1
                continue
            if answer == "yes":
                parent = candidate
                path.append(candidate)
                descended = True
                break
            if answer == "final":
                return candidate, siblings, list(path)
            raise ValueError(f"Unknown answer: {answer!r}")

        if not descended:
            raise PickerError("no_match_at_this_level")


def build_entry(
    confirmed: Any,
    siblings: list[Any],
    path: list[Any],
    *,
    label: str = "",
    index: int = 1,
) -> dict[str, object]:
    """Build one redacted recording entry for a confirmed control.

    `path` is the ancestor chain `walk()` descended through, so the entry
    records how the control was reached and not just what it is.
    """

    described_path = [
        describe_candidate(
            node,
            node_id=f"path_{depth}",
            parent_id=f"path_{depth - 1}" if depth else None,
            depth=depth,
        )
        for depth, node in enumerate(path)
    ]
    depth = len(described_path)
    parent_id = described_path[-1]["node_id"] if described_path else None

    return {
        "entry_index": index,
        "label": sanitize_label(label),
        "path_depth": depth,
        "path": described_path,
        "confirmed": describe_candidate(
            confirmed,
            node_id="confirmed",
            parent_id=parent_id,
            depth=depth,
        ),
        "siblings": [
            describe_candidate(
                sibling,
                node_id=f"sibling_{position}",
                parent_id=parent_id,
                depth=depth,
            )
            for position, sibling in enumerate(siblings)
        ],
    }


def build_recording_report(
    entries: list[dict[str, object]],
) -> dict[str, object]:
    """Wrap every recorded entry in a single redacted report."""

    return {
        "schema_version": 2,
        "picker_version": PICKER_VERSION,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "privacy": {
            "read_only": True,
            "includes_field_values": False,
        },
        "entry_count": len(entries),
        "entries": entries,
    }
