"""Summarise the new concerns and reasons reviewers have proposed.

The Teach bar can capture a label the taxonomy does not contain, but a row in
`dataset.jsonl` teaches the engine nothing on its own - a concern only becomes
predictable once someone writes explicit rules for it in `concerns.json`. This is
the bridge: it tells you what people keep meeting that the config cannot name,
and how often.

Deliberately prints no email text. Counts, names and dates only, so the report
can be pasted into a ticket; the bodies stay in the local dataset file.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from .paths import DATASET_PATH, dataset_dir


def collect(path: str | Path = DATASET_PATH) -> dict[str, dict]:
    """-> {"concerns": {id: {...}}, "reasons": {...}, "rows": n, "path": Path}"""
    p = Path(path)
    concerns: dict[str, dict] = {}
    reasons: dict[str, dict] = {}
    rows = 0

    if not p.exists():
        return {"concerns": concerns, "reasons": reasons, "rows": 0, "path": p}

    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue  # a partially written row must not kill the report
            rows += 1
            label = record.get("label") or {}
            for key, bucket in (("proposed_concern", concerns), ("proposed_reason", reasons)):
                proposed = label.get(key)
                if not proposed:
                    continue
                entry = bucket.setdefault(
                    proposed["id"],
                    {
                        "display_name": proposed.get("display_name", ""),
                        "count": 0,
                        "first_seen": record.get("created_at", ""),
                        "last_seen": record.get("created_at", ""),
                        "notes": [],
                        "predicted_instead": Counter(),
                    },
                )
                entry["count"] += 1
                if key == "proposed_reason":
                    # Which concern it was filed under - a reason block has to
                    # be nested inside one, and the scaffold has to say which.
                    parent = label.get("concern_id")
                    if parent:
                        entry.setdefault("parent_concerns", Counter())[parent] += 1
                created = record.get("created_at", "")
                if created:
                    entry["first_seen"] = min(entry["first_seen"] or created, created)
                    entry["last_seen"] = max(entry["last_seen"], created)
                note = (label.get("reviewer_note") or "").strip()
                if note and note not in entry["notes"]:
                    entry["notes"].append(note)
                predicted = (record.get("prediction") or {}).get("concern_id")
                if key == "proposed_concern":
                    entry["predicted_instead"][predicted or "(nothing)"] += 1

    return {"concerns": concerns, "reasons": reasons, "rows": rows, "path": p}


def format_report(data: dict) -> str:
    lines: list[str] = []
    add = lines.append
    add(f"Dataset: {data['path']}  ({data['rows']} rows)")
    add("")

    for title, bucket in (("PROPOSED CONCERNS", data["concerns"]),
                          ("PROPOSED REASONS", data["reasons"])):
        add(title)
        add("-" * 62)
        if not bucket:
            add("  (none yet)")
        for cid, e in sorted(bucket.items(), key=lambda kv: -kv[1]["count"]):
            add(f"  {cid}   x{e['count']}")
            add(f"      display name : {e['display_name']}")
            add(f"      first seen   : {e['first_seen'][:10]}   "
                f"last: {e['last_seen'][:10]}")
            if e.get("predicted_instead"):
                guessed = ", ".join(
                    f"{k} x{v}" for k, v in e["predicted_instead"].most_common(3)
                )
                add(f"      engine said  : {guessed}")
            for note in e["notes"][:3]:
                add(f"      note         : {note}")
        add("")

    if data["concerns"] or data["reasons"]:
        add("Next step: add each one to src/email_triage/resources/concerns.json")
        add("with positive, negative, and decisive phrase rules, then run")
        add("`python -m email_triage check-config`. Until then")
        add("the engine cannot predict them - it can only record that you asked.")
    return "\n".join(lines)


def report(path: str | Path = DATASET_PATH) -> int:
    data = collect(path)
    text = format_report(data)
    print(text)
    _also_write_when_frozen("proposals.txt", text)
    return 0


# --------------------------------------------------------------------------
# scaffolding an accepted proposal into a concerns.json block
# --------------------------------------------------------------------------


def concern_block(concern_id: str, display_name: str) -> dict:
    """A ready-to-paste `concerns` entry with everything but the thinking.

    Keyword rules are left empty on purpose: a label alone cannot tell us which
    wording is safe, decisive, or likely to collide with another concern.
    `draft: true` makes the unfinished state show up in `check-config` instead
    of looking done.
    """
    return {
        "id": concern_id,
        "display_name": display_name,
        "enabled": True,
        "draft": True,
        "priority": 100,
        "description_internal": "TODO: one line on what this concern means.",
        "keyword_rules": {"positive": [], "negative": [], "decisive": []},
        "structural_gate": {"require_any_pattern": [], "penalty_if_absent": 0.0},
        "reasons": [],
        "fields": [],
    }


def reason_block(reason_id: str, display_name: str) -> dict:
    """A `reasons` entry, to nest inside a concern."""
    return {
        "id": reason_id,
        "display_name": display_name,
        "keyword_rules": {"positive": [], "negative": [], "decisive": []},
    }


def _guidance(kind: str, entry: dict, parent_hint: str) -> str:
    lines = [
        f"Scaffold for proposed {kind}: {entry['display_name']!r}",
        f"Seen {entry['count']}x  (first {entry['first_seen'][:10]}, "
        f"last {entry['last_seen'][:10]})",
        "",
    ]
    if entry.get("notes"):
        lines.append("What reviewers said:")
        lines += [f"  - {n}" for n in entry["notes"][:5]]
        lines.append("")
    if parent_hint:
        lines += [f"Nest this block in the 'reasons' array of: {parent_hint}", ""]

    lines += [
        "The block above is deliberately incomplete. To finish it:",
        "  1. Add 'keyword_rules.positive' phrases that support this label.",
        "  2. Add negative phrases for wording that belongs to another concern.",
        "  3. Add a decisive phrase only when it is unambiguous on its own.",
        "     Use synthetic examples; dataset.jsonl contains real email text.",
    ]
    if kind == "concern":
        lines += [
            "  4. List 'fields' the concern needs, by 'pattern_ref' - never write",
            "     a regex here. Set 'require_label': true on any field whose",
            "     pattern is shared with another field.",
        ]
    lines += [
        "  5. Drop 'draft': true once it is real, then run:",
        "       python -m email_triage check-config",
        "",
        "Until explicit rules exist this label cannot be predicted reliably.",
        "",
        "Nothing was written to concerns.json - paste it yourself, so the config",
        "is never edited by a process that cannot judge whether it is finished.",
    ]
    return "\n".join(lines)


def scaffold(proposed_id: str, path: str | Path = DATASET_PATH) -> int:
    """Print a concerns.json block for a proposal. JSON on stdout, notes on
    stderr, so `--scaffold x > block.json` gives a clean file."""
    data = collect(path)

    if proposed_id in data["concerns"]:
        entry = data["concerns"][proposed_id]
        block = concern_block(proposed_id, entry["display_name"] or proposed_id)
        kind, parent_hint = "concern", ""
    elif proposed_id in data["reasons"]:
        entry = data["reasons"][proposed_id]
        block = reason_block(proposed_id, entry["display_name"] or proposed_id)
        kind = "reason"
        parents = entry.get("parent_concerns")
        parent_hint = parents.most_common(1)[0][0] if parents else "(unknown concern)"
    else:
        known = sorted([*data["concerns"], *data["reasons"]])
        print(f"No proposal named {proposed_id!r} in {data['path']}", file=sys.stderr)
        if known:
            print("Known proposals: " + ", ".join(known), file=sys.stderr)
        else:
            print(
                "No proposals recorded yet. In the Teach bar, pick "
                "'+ new concern...' and name one.",
                file=sys.stderr,
            )
        return 1

    text = json.dumps(block, indent=2, ensure_ascii=False)
    print(text)
    notes = _guidance(kind, entry, parent_hint)
    print("\n" + notes, file=sys.stderr)
    _also_write_when_frozen(f"scaffold_{proposed_id}.json", text)
    return 0


def _also_write_when_frozen(name: str, text: str) -> Path | None:
    """A windowed exe has no console, so stdout goes nowhere. Drop the same
    content beside the executable, the way --selftest already does."""
    if not getattr(sys, "frozen", False):
        return None
    out = dataset_dir().parent / name
    try:
        out.write_text(text, encoding="utf-8")
    except OSError:
        return None
    print(f"(also written to {out})", file=sys.stderr)
    return out
