# jr-dev — single-file edition

`smartadvisor_automation_all_in_one.py` is the whole SmartAdvisor "No Bill on
File" automation in one file, with the design decisions written out as comments.

## Run it

```
pip install pywinauto==0.6.9
python smartadvisor_automation_all_in_one.py
```

Open and sign in to SmartAdvisor **first**. Then fill in Claim ID, DOS From and
Expected Amount and press **Run workflow**.

Python 3.11+. Prefer a **32-bit** Python: SmartAdvisor is a 32-bit application
and the shipped executable is built as x86 for that reason.

## Read it in this order

The file has nine numbered sections, each with a banner explaining its job.
Reading top to bottom is the wrong order — start here:

| Order | Section | Why |
|---|---|---|
| 1 | **7 — The workflow** | The algorithm. Everything else is plumbing. |
| 2 | **4 — Selectors** | Every control, and every trap. |
| 3 | **6 — The driver** | How a control gets clicked or read. |
| 4 | **3 — Data models** | `ControlSpec` and why it has the fields it has. |
| 5 | **8 — The UI** | Threading and the log panel. |
| 6 | **5 — Finding windows** | Skip unless attaching fails. |

The module docstring at the top also has a "THINGS THAT WILL BITE YOU" list.
It is short and worth reading before changing anything.

## The one thing to understand

SmartAdvisor's search-results grid is an owner-drawn control that publishes
**no accessibility information at all** — no rows, no cells, and a description
that never changes when the selection moves. Its contents cannot be read.

So instead of reading the grid, the automation opens each row in turn, reads
the charge amount from the bill itself, and compares. And because returning to
a still-populated grid proved unreliable, **every candidate re-runs the entire
flow from `Ctrl+O`**. That is why a run with several rows is slow — it is
deliberate, not a bug.

## This is a copy

The real project is a normal Python package:

```
src/smartadvisor_automation/
    errors.py  diagnostics.py  models.py  selectors.py
    probe.py   driver.py       workflow.py  app.py
```

That package is what ships, what the 139 unit tests run against, and what the
x86 build uses. **Edits to the single file do not flow back.** If you change
something here and want to keep it, port it to the matching module — each
section banner names its original file — and run:

```
python -m pytest
```

## A note on the log

The Log panel and any saved log **contain charge amounts**, on purpose: masking
them made a wrong value and a right value look identical and caused a real
misdiagnosis. Treat saved logs as sensitive and don't paste them into tickets,
chat or email. Claim ID, DOS and Patient Account are never logged.
