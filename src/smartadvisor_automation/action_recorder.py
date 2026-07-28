"""Turn observed operator input into a redacted, replayable step list.

The recorder watches a real SmartAdvisor session and records what was
done, not what was typed. Each step carries everything
`SmartAdvisorDriver` needs to reproduce it:

- the target's `automation_id`, which is the entire selector model
  (`ControlSpec.automation_id`);
- `match_count` at record time, because `SmartAdvisorDriver.resolve()`
  requires exactly one visible and enabled match and otherwise fails with
  `selector_ambiguous`/`selector_not_found`;
- the ancestor chain and owning window, so a step that lives in a new
  modal is recognisable as such;
- the delay before the target became actionable, to check it against the
  driver's 12 s resolve timeout.

Typed characters are never captured. A text entry is recorded as "this
control received typing", and the value is supplied at run time from a
workflow parameter, exactly as `claim_id` and `dos_from` already are.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from smartadvisor_automation.control_picker import (
    describe_candidate,
    sanitize_label,
)
from smartadvisor_automation.object_extractor import sanitize_name

RECORDER_VERSION = "0.1.0"
MAX_CHAIN_DEPTH = 12
MAX_STEPS = 500
MAX_MATCH_SCAN = 4000


class ElementRef:
    """Adapt a bare UIA element info to the `.element_info` protocol.

    `describe_candidate` and `probe.matching_elements` both expect a
    wrapper-shaped object; constructing a real `UIAWrapper` can raise on
    odd elements, so this shim is used instead.
    """

    __slots__ = ("element_info",)

    def __init__(self, element_info: Any) -> None:
        self.element_info = element_info


@dataclass
class ResolvedTarget:
    """A control identified at the moment an action happened."""

    element: Any
    chain: list[Any] = field(default_factory=list)
    window: Any | None = None
    match_count: int | None = None


def _automation_id(target: ResolvedTarget | None) -> str:
    if target is None:
        return ""
    info = target.element.element_info
    return str(getattr(info, "automation_id", "") or "")


def describe_window(window: Any | None) -> dict[str, object] | None:
    """Describe an owning window structurally, with its name sanitized."""

    if window is None:
        return None
    info = window.element_info
    return {
        "automation_id": str(getattr(info, "automation_id", "") or ""),
        "control_type": str(getattr(info, "control_type", "") or ""),
        "class_name": str(getattr(info, "class_name", "") or ""),
        "name": sanitize_name(getattr(info, "name", "")),
    }


def describe_target(target: ResolvedTarget | None) -> dict[str, object] | None:
    """Describe an action's target, including its resolvability."""

    if target is None:
        return None
    described = describe_candidate(
        target.element,
        node_id="target",
        parent_id="path_last",
        depth=len(target.chain),
    )
    described["match_count"] = target.match_count
    described["uniquely_resolvable"] = (
        None if target.match_count is None else target.match_count == 1
    )
    described["automatable"] = bool(_automation_id(target))
    return described


def describe_chain(target: ResolvedTarget | None) -> list[dict[str, object]]:
    """Describe the ancestor chain, outermost first."""

    if target is None:
        return []
    return [
        describe_candidate(
            node,
            node_id=f"path_{depth}",
            parent_id=f"path_{depth - 1}" if depth else None,
            depth=depth,
        )
        for depth, node in enumerate(target.chain)
    ]


class ActionRecorder:
    """Aggregate raw input events into ordered, redacted steps.

    The resolver is injected so the aggregation logic is testable without
    pywinauto: it must provide `from_point(x, y)` and `focused()`, each
    returning a `ResolvedTarget` or None.
    """

    def __init__(
        self,
        resolver: Any,
        *,
        clock: Any = time.monotonic,
        ignore_process_id: int | None = None,
    ) -> None:
        self.resolver = resolver
        self.clock = clock
        # The recorder's own window is driven by the same mouse and
        # keyboard, so its controls must never become steps.
        self.ignore_process_id = ignore_process_id
        self.steps: list[dict[str, object]] = []
        self.skipped: list[dict[str, object]] = []
        self._pending: ResolvedTarget | None = None
        self._pending_at: float | None = None
        self._last_at: float | None = None
        self._last_window: dict[str, object] | None = None

    # -- event handling ------------------------------------------------

    def handle_click(self, button: str, x: int, y: int, at: float) -> None:
        """Record a mouse click on whatever control was under the cursor."""

        self.flush_pending()
        target = self._safe(lambda: self.resolver.from_point(x, y))
        self._append(
            action="click",
            at=at,
            target=target,
            button=button,
        )

    def handle_chord(self, keys: str, at: float) -> None:
        """Record a structural key press or accelerator, e.g. `^o`."""

        self.flush_pending()
        target = self._safe(self.resolver.focused)
        self._append(action="key", at=at, target=target, keys=keys)

    def handle_char(self, at: float) -> None:
        """Note that a character key reached the focused control.

        The character itself is never read. Consecutive characters in the
        same control collapse into a single `input` step, flushed when the
        operator clicks, presses a structural key, or stops recording.
        """

        if self._pending is not None:
            return
        target = self._safe(self.resolver.focused)
        if self._is_own_ui(target):
            return
        if target is None:
            self.skipped.append(
                {"action": "input", "reason": "focused_control_unresolved"}
            )
            return
        self._pending = target
        self._pending_at = at

    def flush_pending(self) -> None:
        """Emit the pending typing step, if any."""

        if self._pending is None:
            return
        target = self._pending
        at = self._pending_at
        self._pending = None
        self._pending_at = None
        self._append(
            action="input",
            at=at if at is not None else self.clock(),
            target=target,
            value={"status": "not_recorded", "source": "run_parameter"},
        )

    def handle_event(self, event: tuple[Any, ...]) -> None:
        """Dispatch one raw `InputHookListener` event tuple."""

        kind = event[0]
        if kind == "click":
            _, button, x, y, at = event
            self.handle_click(button, x, y, at)
        elif kind == "chord":
            _, keys, at = event
            self.handle_chord(keys, at)
        elif kind == "char":
            self.handle_char(event[1])

    # -- step assembly -------------------------------------------------

    def _append(
        self,
        *,
        action: str,
        at: float,
        target: ResolvedTarget | None,
        button: str | None = None,
        keys: str | None = None,
        value: dict[str, object] | None = None,
    ) -> None:
        if len(self.steps) >= MAX_STEPS:
            return
        if self._is_own_ui(target):
            return

        window = describe_window(target.window if target else None)
        opened_new_window = bool(
            window is not None and window != self._last_window
        )
        since_previous = (
            None if self._last_at is None else round(at - self._last_at, 3)
        )

        self.steps.append(
            {
                "step_index": len(self.steps) + 1,
                "action": action,
                "label": "",
                "button": button,
                "keys": keys,
                "value": value,
                "seconds_since_previous": since_previous,
                "window": window,
                "opened_new_window": opened_new_window,
                "path": describe_chain(target),
                "target": describe_target(target),
            }
        )
        self._last_at = at
        if window is not None:
            self._last_window = window

    def label_step(self, step_index: int, label: str) -> None:
        """Attach an operator-supplied structural label to one step."""

        for step in self.steps:
            if step["step_index"] == step_index:
                step["label"] = sanitize_label(label)
                return

    def drop_step(self, step_index: int) -> None:
        """Remove a mis-recorded step and renumber the rest."""

        self.steps = [
            step for step in self.steps if step["step_index"] != step_index
        ]
        for position, step in enumerate(self.steps, start=1):
            step["step_index"] = position

    def clear(self) -> None:
        self.steps = []
        self.skipped = []
        self._pending = None
        self._pending_at = None
        self._last_at = None
        self._last_window = None

    def _is_own_ui(self, target: ResolvedTarget | None) -> bool:
        if target is None or self.ignore_process_id is None:
            return False
        try:
            process_id = getattr(
                target.element.element_info, "process_id", None
            )
            return int(process_id) == int(self.ignore_process_id)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _safe(call: Any) -> ResolvedTarget | None:
        try:
            return call()
        except Exception:
            return None


def build_action_report(
    steps: list[dict[str, object]],
    *,
    skipped: list[dict[str, object]] | None = None,
    notes: str = "",
) -> dict[str, object]:
    """Wrap recorded steps in one redacted report."""

    unresolved = [
        step["step_index"]
        for step in steps
        if step.get("target") is None
        or not step["target"].get("automatable")
    ]
    ambiguous = [
        step["step_index"]
        for step in steps
        if step.get("target") is not None
        and step["target"].get("uniquely_resolvable") is False
    ]

    return {
        "schema_version": 1,
        "recorder_version": RECORDER_VERSION,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "privacy": {
            "read_only": True,
            "includes_field_values": False,
            "includes_typed_characters": False,
            "includes_unknown_names": False,
            "name_policy": "structural_allowlist_otherwise_redacted",
        },
        "notes": sanitize_label(notes),
        "step_count": len(steps),
        "review": {
            "steps_without_automation_id": unresolved,
            "steps_not_uniquely_resolvable": ambiguous,
        },
        "steps": steps,
        "skipped": list(skipped or []),
    }


class UiaResolver:
    """Resolve screen points and focus to UIA elements, with ancestors.

    Every pywinauto import is deferred to call time so the aggregation
    logic above can be tested without it.
    """

    def __init__(self, backend: str = "uia") -> None:
        self.backend = backend

    def from_point(self, x: int, y: int) -> ResolvedTarget | None:
        from pywinauto.uia_element_info import UIAElementInfo

        try:
            info = UIAElementInfo.from_point(x, y)
        except Exception:
            return None
        return self._build(info)

    def focused(self) -> ResolvedTarget | None:
        from pywinauto.uia_defines import IUIA
        from pywinauto.uia_element_info import UIAElementInfo

        try:
            info = UIAElementInfo(IUIA().get_focused_element())
        except Exception:
            return None
        return self._build(info)

    def _build(self, info: Any) -> ResolvedTarget | None:
        if info is None:
            return None
        element = ElementRef(info)
        chain = self._ancestors(info)
        window = chain[0] if chain else element
        automation_id = str(getattr(info, "automation_id", "") or "")
        return ResolvedTarget(
            element=element,
            chain=chain,
            window=window,
            match_count=(
                self.count_matches(automation_id, info)
                if automation_id
                else None
            ),
        )

    @staticmethod
    def _ancestors(info: Any) -> list[Any]:
        """Walk up to the top-level window, outermost first."""

        chain: list[Any] = []
        current = info
        for _ in range(MAX_CHAIN_DEPTH):
            try:
                parent = current.parent
            except Exception:
                break
            if parent is None:
                break
            if not str(getattr(parent, "class_name", "") or ""):
                # The desktop root has no class name worth recording.
                break
            chain.append(ElementRef(parent))
            current = parent
        chain.reverse()
        return chain

    def count_matches(self, automation_id: str, info: Any) -> int | None:
        """Count visible, enabled matches the way `resolve()` would.

        Mirrors `SmartAdvisorDriver._all_elements` - every visible
        top-level window of the process plus its descendants - so a
        recorded step can be checked against the driver's
        exactly-one-match contract before any code is written.
        """

        from pywinauto import Desktop

        from smartadvisor_automation.probe import matching_elements

        process_id = getattr(info, "process_id", None)
        if not automation_id or process_id is None:
            return None

        try:
            windows = list(
                Desktop(backend=self.backend).windows(
                    process=process_id,
                    visible_only=True,
                    enabled_only=False,
                )
            )
        except Exception:
            return None

        elements: list[Any] = []
        for window in windows:
            elements.append(window)
            try:
                elements.extend(window.descendants())
            except Exception:
                continue
            if len(elements) > MAX_MATCH_SCAN:
                return None

        try:
            matches = matching_elements(elements, automation_id)
        except Exception:
            return None

        actionable = 0
        for element, _strategy in matches:
            try:
                if element.is_visible() and element.is_enabled():
                    actionable += 1
            except Exception:
                continue
        return actionable
