"""Headless check that the frozen bundle actually works.

A windowed exe swallows stdout and shows tracebacks in a modal, so this writes
a report next to the executable instead. Also the field-diagnostic for "it
won't start on this machine".

Imports nothing from the UI - it exercises the engine only, which is what the
bundle is really being asked to prove.
"""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

# The message the bundle must reproduce: all seven fields, with DOS/DOI/DOB
# kept distinct. That is the result this build is most likely to regress on.
SAMPLE_SUBJECT = "Bill status"
SAMPLE_BODY = (
    "Bill status please.\n"
    "Claim ID: WC7788991\n"
    "DOS: 05/01/2026\n"
    "DOI: 04/02/2026\n"
    "DOB: 11/30/1979\n"
    "Prov TIN: 98-7654321\n"
    "Patient Account: PA5512399\n"
    "Expected amount: $3,410.55\n"
)
EXPECTED_VALUES = {
    "claim_id": "WC7788991",
    "date_of_service": "2026-05-01",
    "date_of_injury": "2026-04-02",
    "date_of_birth": "1979-11-30",
    "provider_tin": "987654321",
    "patient_account": "PA5512399",
    "expected_amount": "3410.55",
}


def selftest() -> int:
    report: dict = {
        "python": sys.version,
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable": sys.executable,
        "machine": platform.machine(),
        "resources_dir": None,
        "ok": False,
    }
    try:
        from email_triage.config import RESOURCES
        from email_triage.engine import TriageEngine

        report["resources_dir"] = str(RESOURCES)
        report["resources_exist"] = RESOURCES.is_dir()

        eng = TriageEngine()
        report["layers"] = list(eng.layers_used)
        report["concern_ids"] = list(eng.concern_ids)

        r = eng.classify(SAMPLE_BODY, subject=SAMPLE_SUBJECT)
        report["result"] = {
            "concern_id": r.concern_id,
            "reason_id": r.reason_id,
            "status": r.status.value,
            "confidence": round(r.confidence, 3),
            "values": r.values,
            "elapsed_ms": round(r.elapsed_ms, 1),
        }
        report["ok"] = r.concern_id == "bill_status" and r.values == EXPECTED_VALUES
    except Exception as exc:
        import traceback

        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()

    base = (
        Path(sys.executable).resolve().parent
        if getattr(sys, "frozen", False)
        else Path.cwd()
    )
    out = base / "selftest.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1
