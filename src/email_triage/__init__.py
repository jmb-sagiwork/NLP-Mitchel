"""email_triage - offline email concern classification and field extraction.

Public surface only. Everything re-exported here is a stable contract; anything
else is internal and may move.
"""

from __future__ import annotations

__version__ = "0.2.20"

from .api import classify_email, classify_emails  # noqa: E402
from .engine import TriageEngine, get_default_engine  # noqa: E402
from .errors import ConfigError, ModelUnavailable, TriageError  # noqa: E402
from .render import (  # noqa: E402
    append_training_record,
    build_training_record,
    slugify_label,
    to_json,
    to_plain_text,
)
from .types import FieldValue, TriageResult, TriageStatus  # noqa: E402

__all__ = [
    "__version__",
    "classify_email",
    "classify_emails",
    "TriageEngine",
    "get_default_engine",
    "TriageResult",
    "TriageStatus",
    "FieldValue",
    "to_plain_text",
    "to_json",
    "build_training_record",
    "append_training_record",
    "slugify_label",
    "TriageError",
    "ConfigError",
    "ModelUnavailable",
]
