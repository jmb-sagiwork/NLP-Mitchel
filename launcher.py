"""Frozen-app entry point.

PyInstaller runs its entry script as __main__ with no package context, so the
script it freezes must import the package absolutely - pointing the spec at
email_triage_ui/app.py directly breaks every relative import inside it.

Routes through the package CLI rather than straight to the window, so the
frozen exe gets --selftest, --proposals and --scaffold too.
"""

from __future__ import annotations

import sys

from email_triage_ui.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
