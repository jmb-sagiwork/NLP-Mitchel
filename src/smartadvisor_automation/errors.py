from __future__ import annotations


class AutomationError(RuntimeError):
    """A sanitized automation failure safe to show in the UI."""

    def __init__(
        self,
        code: str,
        *,
        step: str | None = None,
        diagnostics: dict[str, object] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.step = step
        self.diagnostics = diagnostics


class WorkflowCancelled(RuntimeError):
    """Raised when the user cancels between workflow steps."""

