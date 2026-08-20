"""Headless validation for the frozen combined Mitchel application."""

from __future__ import annotations

import json
import platform
import sys
import traceback
from pathlib import Path

SAMPLE_SUBJECT = "Bill status"
SAMPLE_BODY = (
    "Bill status request.\n"
    "Claim ID: WC7788991\n"
    "DOS: 05/01/2026\n"
    "Expected amount: $3,410.55\n"
)


def _report_path() -> Path:
    base = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path.cwd()
    )
    return base / "mitchel-selftest.json"


def selftest() -> int:
    report: dict[str, object] = {
        "python": sys.version,
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable": sys.executable,
        "machine": platform.machine(),
        "nlp_ok": False,
        "helper_ok": False,
        "selenium_ok": False,
        "ok": False,
    }

    helper = None
    try:
        import selenium

        from email_triage import TriageEngine, classify_email

        from .helper_client import SmartAdvisorHelperClient
        from .jobs import jobs_from_result

        report["selenium_ok"] = True
        report["selenium_version"] = selenium.__version__

        engine = TriageEngine(enable_embeddings=True)
        result = classify_email(SAMPLE_BODY, SAMPLE_SUBJECT, engine=engine)
        jobs = jobs_from_result(result, "selftest-email")
        report["embeddings_active"] = engine.embeddings_active
        report["layers"] = list(engine.layers_used)
        report["classification"] = {
            "status": result.status.value,
            "concern_id": result.concern_id,
            "values": result.values,
            "jobs": [job.to_dict() for job in jobs],
        }
        report["nlp_ok"] = (
            engine.embeddings_active
            and result.concern_id == "bill_status"
            and len(jobs) == 1
            and jobs[0].claim_id == "WC7788991"
            and jobs[0].dos_from == "05/01/2026"
            and jobs[0].expected_amount == "3410.55"
        )

        helper = SmartAdvisorHelperClient()
        helper.start()
        report["helper_ok"] = True
        report["ok"] = bool(
            report["nlp_ok"] and report["helper_ok"] and report["selenium_ok"]
        )
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
    finally:
        if helper is not None:
            helper.close()

    output = _report_path()
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1
