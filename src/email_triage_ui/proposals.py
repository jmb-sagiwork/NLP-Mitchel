"""Summarise the new concerns and reasons reviewers have proposed.

The Teach bar can capture a label the taxonomy does not contain, but a row in
`dataset.jsonl` teaches the engine nothing on its own - a concern only becomes
predictable once someone writes prototypes for it in `concerns.json`. This is
the bridge: it tells you what people keep meeting that the config cannot name,
and how often.

Deliberately prints no email text. Counts, names and dates only, so the report
can be pasted into a ticket; the bodies stay in the local dataset file.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .paths import DATASET_PATH


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
        add("with 3-5 prototypes (plain-English descriptions of what the sender")
        add("wants), then run `python -m email_triage check-config`. Until then")
        add("the engine cannot predict them - it can only record that you asked.")
    return "\n".join(lines)


def report(path: str | Path = DATASET_PATH) -> int:
    data = collect(path)
    print(format_report(data))
    return 0
