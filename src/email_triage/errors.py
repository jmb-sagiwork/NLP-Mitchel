"""Exception tree. Messages must never embed email text or field values."""

from __future__ import annotations


class TriageError(Exception):
    """Base for every error this package raises."""

    code = "TRIAGE_ERROR"


class ConfigError(TriageError):
    code = "CONFIG_ERROR"


class PatternError(ConfigError):
    code = "PATTERN_ERROR"


class ModelUnavailable(TriageError):
    """Layer 3 could not load. The engine degrades rather than failing."""

    code = "MODEL_UNAVAILABLE"


class MailSourceError(TriageError):
    code = "MAIL_SOURCE_ERROR"
