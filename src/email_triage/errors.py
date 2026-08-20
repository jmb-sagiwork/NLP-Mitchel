"""Exception tree. Messages must never embed email text or field values."""

from __future__ import annotations


class TriageError(Exception):
    """Base for every error this package raises."""

    code = "TRIAGE_ERROR"


class ConfigError(TriageError):
    code = "CONFIG_ERROR"


class PatternError(ConfigError):
    code = "PATTERN_ERROR"


class MailSourceError(TriageError):
    code = "MAIL_SOURCE_ERROR"
