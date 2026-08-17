"""Where the teaching harness keeps captured rows.

Its own module so the proposals report can find the file without importing
tkinter - a frozen console run of `--proposals` should not build a window.
"""

from __future__ import annotations

import sys
from pathlib import Path


def dataset_dir() -> Path:
    """Frozen: beside the .exe, so the file is where the operator expects it
    and never in a temp dir that gets cleaned. From source: the project's
    data/. This file holds real email text - see pipeline SP-1.1-44."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "data"
    return Path.cwd() / "data"


DATASET_PATH = dataset_dir() / "dataset.jsonl"
