"""Frozen-app entry point.

PyInstaller runs its entry script as __main__ with no package context, so the
script it freezes must import the package absolutely - pointing the spec at
ui/app.py directly breaks every relative import inside it.
"""

from __future__ import annotations

from email_triage.ui.app import main

if __name__ == "__main__":
    main()
