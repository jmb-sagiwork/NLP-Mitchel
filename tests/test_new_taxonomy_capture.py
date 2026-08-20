"""Naming a concern the taxonomy does not have yet.

The Teach bar's dropdown can only offer what `concerns.json` already contains,
so before SP-1.1-56 a reviewer meeting a genuinely new category could say only
`__other__` - which records that the answer was wrong without recording what
the answer was. These tests cover the capture path that replaced it.
"""

from __future__ import annotations

import json
from pathlib import Path

from email_triage.render import (
    append_training_record,
    build_training_record,
    slugify_label,
)
from email_triage_ui.proposals import collect, format_report, scaffold

BODY = "Bill status for Claim ID WC1234567, DOS 03/14/2026."


def test_slugify_turns_a_typed_name_into_a_config_id():
    assert slugify_label("Refund Request") == "refund_request"
    assert slugify_label("  Appeal / Reconsideration  ") == "appeal_reconsideration"
    assert slugify_label("EOB (paper)") == "eob_paper"
    assert slugify_label("!!!") == ""


def test_proposed_concern_becomes_the_label_and_is_flagged(rules_engine):
    r = rules_engine.classify(BODY)
    rec = build_training_record(BODY, "", r, proposed_concern="Refund Request")
    label = rec["label"]
    assert label["concern_id"] == "refund_request"
    assert label["proposed_concern"] == {
        "id": "refund_request",
        "display_name": "Refund Request",
    }
    assert label["is_new_taxonomy"] is True
    assert label["verified_by_human"] is True
    assert label["was_prediction_correct"] is False
    # The engine's own answer survives for error analysis.
    assert rec["prediction"]["concern_id"] == "bill_status"


def test_proposed_reason_is_independent_of_the_concern(rules_engine):
    r = rules_engine.classify(BODY)
    rec = build_training_record(BODY, "", r, proposed_reason="Awaiting medical records")
    label = rec["label"]
    assert label["concern_id"] == r.concern_id  # concern was right
    assert label["reason_id"] == "awaiting_medical_records"
    assert label["proposed_concern"] is None
    assert label["is_new_taxonomy"] is True


def test_an_ordinary_correction_is_not_flagged_as_new_taxonomy(rules_engine):
    r = rules_engine.classify(BODY)
    rec = build_training_record(BODY, "", r, corrected_concern_id="claim_information")
    assert rec["label"]["is_new_taxonomy"] is False
    assert rec["label"]["proposed_concern"] is None


def test_proposals_report_counts_and_hides_email_text(rules_engine, tmp_path):
    r = rules_engine.classify(BODY)
    path = tmp_path / "dataset.jsonl"
    for _ in range(2):
        append_training_record(
            build_training_record(
                BODY, "", r, proposed_concern="Refund Request",
                reviewer_note="third time this week",
            ),
            path,
        )
    append_training_record(
        build_training_record(BODY, "", r, proposed_reason="Awaiting records"), path
    )

    data = collect(path)
    assert data["rows"] == 3
    assert data["concerns"]["refund_request"]["count"] == 2
    assert data["reasons"]["awaiting_records"]["count"] == 1
    assert data["concerns"]["refund_request"]["predicted_instead"]["bill_status"] == 2

    text = format_report(data)
    assert "refund_request" in text
    assert "third time this week" in text
    # The point of the report is that it can leave the machine. The body cannot.
    assert BODY not in text
    assert "WC1234567" not in text


def test_report_survives_a_half_written_row(tmp_path):
    path = tmp_path / "dataset.jsonl"
    path.write_text('{"label": {}}\n{"label": {"proposed_conc\n', encoding="utf-8")
    data = collect(path)
    assert data["rows"] == 1


def test_report_on_a_missing_dataset_is_not_an_error(tmp_path):
    data = collect(tmp_path / "nope.jsonl")
    assert data["rows"] == 0
    assert "(none yet)" in format_report(data)


# ---------------------------------------------------------------- scaffolding


def _dataset_with_a_proposal(tmp_path, engine, **kw):
    r = engine.classify(BODY)
    path = tmp_path / "dataset.jsonl"
    append_training_record(build_training_record(BODY, "", r, **kw), path)
    return path


def test_scaffold_emits_a_pasteable_concern_block(rules_engine, tmp_path, capsys):
    path = _dataset_with_a_proposal(
        tmp_path, rules_engine, proposed_concern="Refund Request"
    )
    assert scaffold("refund_request", path) == 0

    out = capsys.readouterr()
    block = json.loads(out.out)          # stdout is clean JSON, nothing else
    assert block["id"] == "refund_request"
    assert block["display_name"] == "Refund Request"
    # Empty on purpose: safe phrase rules cannot be derived from a label.
    assert block["keyword_rules"] == {
        "positive": [], "negative": [], "decisive": []
    }
    assert block["draft"] is True
    assert "keyword_rules" in out.err       # guidance goes to stderr


def test_scaffold_of_a_reason_names_the_concern_to_nest_it_in(rules_engine, tmp_path, capsys):
    path = _dataset_with_a_proposal(
        tmp_path, rules_engine, proposed_reason="Awaiting records"
    )
    assert scaffold("awaiting_records", path) == 0

    out = capsys.readouterr()
    block = json.loads(out.out)
    assert block["id"] == "awaiting_records"
    assert "reasons" not in block        # a reason block nests, it is not a concern
    assert "bill_status" in out.err      # the concern it was filed under


def test_scaffold_never_leaks_email_text(rules_engine, tmp_path, capsys):
    path = _dataset_with_a_proposal(
        tmp_path, rules_engine, proposed_concern="Refund Request",
        reviewer_note="claimant called twice",
    )
    scaffold("refund_request", path)
    out = capsys.readouterr()
    assert BODY not in out.out + out.err
    assert "WC1234567" not in out.out + out.err
    assert "claimant called twice" in out.err   # reviewer notes are shown


def test_scaffold_does_not_touch_concerns_json(rules_engine, tmp_path, capsys):
    """A block with no rules would classify nothing while looking done."""
    config = Path(__file__).resolve().parents[1] / (
        "src/email_triage/resources/concerns.json"
    )
    before = config.read_bytes()
    path = _dataset_with_a_proposal(
        tmp_path, rules_engine, proposed_concern="Refund Request"
    )
    scaffold("refund_request", path)
    capsys.readouterr()
    assert config.read_bytes() == before


def test_scaffold_of_an_unknown_id_fails_and_lists_what_exists(
    rules_engine, tmp_path, capsys
):
    path = _dataset_with_a_proposal(
        tmp_path, rules_engine, proposed_concern="Refund Request"
    )
    assert scaffold("no_such_thing", path) == 1
    err = capsys.readouterr().err
    assert "no_such_thing" in err
    assert "refund_request" in err
