"""The engine must be embeddable in a host app that has no UI at all.

These are the tests that keep SP-1.1-52 from quietly rotting: a stray
`from email_triage_ui...` or a module-scope `import tkinter` inside the engine
would make the library undeployable on a headless host, and nothing else in the
suite would notice.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
ENGINE = SRC / "email_triage"


def _engine_modules() -> list[Path]:
    return sorted(p for p in ENGINE.rglob("*.py"))


def test_no_engine_module_imports_the_ui_package():
    # Mentioning it in help text is fine; importing it is not.
    offenders = [
        p.relative_to(SRC).as_posix()
        for p in _engine_modules()
        if re.search(r"^\s*(from|import)\s+email_triage_ui", p.read_text(encoding="utf-8"), re.M)
    ]
    assert offenders == []


def test_no_engine_module_imports_tkinter():
    offenders = [
        p.relative_to(SRC).as_posix()
        for p in _engine_modules()
        if "import tkinter" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []


def _comparable(result) -> dict:
    """Everything but the wall-clock timing, which never repeats exactly."""
    d = result.to_dict()
    d.pop("elapsed_ms", None)
    return d


def test_importing_the_engine_does_not_pull_in_tkinter():
    """Run in a subprocess: an in-process check would pass just because some
    earlier test never imported tkinter either."""
    code = (
        "import sys; sys.path.insert(0, r'%s');"
        "import email_triage;"
        "print('tkinter' in sys.modules)" % SRC
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=180
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False"


def test_classify_email_takes_body_and_subject_positionally(engine):
    """The whole host-facing contract is two strings, in either calling style."""
    from email_triage import classify_email

    body = "Claim ID: WC7788991\nPlease advise on the bill.\n"
    positional = classify_email(body, "Bill status", engine=engine)
    keyword = classify_email(body, subject="Bill status", engine=engine)
    assert _comparable(positional) == _comparable(keyword)


def test_classify_emails_accepts_mappings(engine):
    from email_triage import classify_emails

    body = "Bill status please. Claim ID: WC7788991\n"
    from_tuples = classify_emails([(body, "Bill status")], engine=engine)
    from_dicts = classify_emails([{"body": body, "subject": "Bill status"}], engine=engine)
    assert _comparable(from_tuples[0]) == _comparable(from_dicts[0])
