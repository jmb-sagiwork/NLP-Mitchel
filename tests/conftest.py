from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from email_triage.engine import TriageEngine  # noqa: E402


@pytest.fixture(scope="session")
def engine() -> TriageEngine:
    """Full engine, embeddings if the model is present."""
    return TriageEngine()


@pytest.fixture(scope="session")
def rules_engine() -> TriageEngine:
    """Deterministic layers only. Every assertion here must hold offline and
    with no model file, which is the guaranteed-available configuration."""
    return TriageEngine(enable_embeddings=False)
