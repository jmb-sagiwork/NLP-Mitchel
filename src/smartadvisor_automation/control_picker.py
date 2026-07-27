from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from smartadvisor_automation.object_extractor import _uia_node
from smartadvisor_automation.probe import find_smartadvisor_window

PICKER_VERSION = "0.1.0"


class PickerError(RuntimeError):
    """A sanitized control-picker failure safe to show in the UI."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def describe_candidate(wrapper: Any) -> dict[str, object]:
    """Return the same privacy-safe fields the object extractor records."""

    return _uia_node(
        "uia",
        wrapper.element_info,
        node_id="candidate",
        parent_id=None,
        depth=0,
    )


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
      and `(candidate, siblings)` is available as the StopIteration value.

    Raises PickerError if a level has no children, or every sibling at a
    level is answered "no" without ever reaching "yes" or "final".
    """

    parent = root
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
                descended = True
                break
            if answer == "final":
                return candidate, siblings
            raise ValueError(f"Unknown answer: {answer!r}")

        if not descended:
            raise PickerError("no_match_at_this_level")


def build_report(
    confirmed: Any, siblings: list[Any]
) -> dict[str, object]:
    """Build the redacted report for the confirmed final control."""

    return {
        "schema_version": 1,
        "picker_version": PICKER_VERSION,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "privacy": {
            "read_only": True,
            "includes_field_values": False,
        },
        "confirmed": describe_candidate(confirmed),
        "siblings": [describe_candidate(sibling) for sibling in siblings],
    }
