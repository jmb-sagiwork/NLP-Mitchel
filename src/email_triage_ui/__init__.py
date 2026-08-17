"""Teaching harness for the triage engine.

A separate top-level package on purpose. `email_triage` is the deliverable a
host application imports; this is the operator-facing window used to feed the
engine examples and capture corrections. Nothing in `email_triage` imports
anything from here, so a host can vendor the engine alone.
"""

from __future__ import annotations

from .app import main
from .selftest import selftest

__all__ = ["main", "selftest"]
