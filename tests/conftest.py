from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from email_triage.engine import TriageEngine  # noqa: E402


@pytest.fixture(scope="session")
def engine() -> TriageEngine:
    """The production rules + structural engine."""
    return TriageEngine()


@pytest.fixture(scope="session")
def rules_engine() -> TriageEngine:
    """Compatibility fixture name for tests written around the rules engine."""
    return TriageEngine()
