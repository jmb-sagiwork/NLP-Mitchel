"""Launch the demo UI without installing the package.

    py -3.14 run_ui.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from email_triage.ui import main  # noqa: E402

if __name__ == "__main__":
    main()
