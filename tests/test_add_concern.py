"""The load-bearing test.

The product claim is: a new concern type is added by editing JSON, with no code
change and no retraining. If this test ever becomes awkward to write, the config
design has failed - see pipeline SP-1.1-36.
"""

from __future__ import annotations

import json
import shutil

from email_triage.config import CONCERNS_PATH, PATTERNS_PATH
from email_triage.engine import TriageEngine


def test_new_concern_type_needs_only_a_json_edit(tmp_path):
    shutil.copy(PATTERNS_PATH, tmp_path / "patterns.library.json")
    cfg = json.loads(CONCERNS_PATH.read_text(encoding="utf-8"))

    before = TriageEngine(config_path=CONCERNS_PATH)
    assert "mileage_reimbursement" not in before.concern_ids

    # Everything below is data. No Python is written to teach the new concern.
    cfg["concerns"].append({
        "id": "mileage_reimbursement",
        "display_name": "Mileage Reimbursement",
        "enabled": True,
        "priority": 50,
        "keyword_rules": {
            "positive": [
                {"phrase": "mileage reimbursement", "weight": 4.0},
                {"phrase": "mileage", "weight": 2.0},
                {"phrase": "miles driven", "weight": 2.0},
            ],
            "negative": [],
            "decisive": [{"all_of": ["mileage reimbursement"]}],
        },
        "structural_gate": {
            "require_any_pattern": ["claim_id"],
            "penalty_if_absent": 0.25,
        },
        "fields": [
            {
                "name": "claim_number",
                "display_name": "Claim Number",
                "required": True,
                "pattern_ref": "claim_id",
                "label_aliases": ["claim number", "claim #", "claim"],
                "normalizer": "upper_alnum",
            },
            {
                "name": "travel_date",
                "display_name": "Travel Date",
                "required": True,
                "pattern_ref": "us_date",
                "label_aliases": ["date of travel", "travel date", "date"],
                "normalizer": "date_iso",
            },
        ],
    })

    new_path = tmp_path / "concerns.json"
    new_path.write_text(json.dumps(cfg), encoding="utf-8")

    after = TriageEngine(config_path=new_path)
    assert "mileage_reimbursement" in after.concern_ids

    r = after.classify(
        "Submitting a mileage reimbursement request for claim WC1234567, "
        "travel date 03/14/2026."
    )
    assert r.concern_id == "mileage_reimbursement"
    assert r.values["claim_number"] == "WC1234567"
    assert r.values["travel_date"] == "2026-03-14"
    assert not r.missing_fields


def test_disabling_a_concern_removes_it_from_scoring(tmp_path):
    shutil.copy(PATTERNS_PATH, tmp_path / "patterns.library.json")
    cfg = json.loads(CONCERNS_PATH.read_text(encoding="utf-8"))
    for c in cfg["concerns"]:
        if c["id"] == "bill_status":
            c["enabled"] = False
    p = tmp_path / "concerns.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")

    eng = TriageEngine(config_path=p)
    assert "bill_status" not in eng.concern_ids
    r = eng.classify("Bill status for Claim ID WC1234567, DOS 03/14/2026.")
    assert r.concern_id != "bill_status"
