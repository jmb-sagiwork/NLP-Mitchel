# Recent Conversation Handoff

Last updated: 2026-07-29 (Asia/Manila)

## Current repository state

- Repository: `jmb-sagiwork/Sagi-SmartAdvisor`
- Branch: `main`
- Last confirmed pushed state: synchronized with `origin/main`
- Latest pushed commit before this handoff update:
  `600fae9` — `Reuse robust SmartAdvisor window attachment`
- Current automation executable:
  `release/SmartAdvisorAutomation-0.3.5-x86.exe`
- Download:
  `https://github.com/jmb-sagiwork/Sagi-SmartAdvisor/raw/refs/heads/main/release/SmartAdvisorAutomation-0.3.5-x86.exe`
- SHA-256:
  `04fcd5629a3ca1806921fa827114a4be5956232f19f566ad922ef01cb4137be1`
- PE architecture: x86 (`0x014c`)
- Validation: 77 tests passed locally and in GitHub Actions
- Successful build:
  `https://github.com/jmb-sagiwork/Sagi-SmartAdvisor/actions/runs/30385754027`

The local computer only has 64-bit Python. Citrix-compatible x86 executables
are built using `.github/workflows/build-x86.yml`, downloaded from the
successful GitHub Actions run, independently checked, and committed into
`release/`.

The Bill Search diagnostic utility is intentionally x64 because local Python
is x64; UIA can inspect the 32-bit target across bitness:

- Executable: `release/BillSearchControlPrinter-0.1.2-x64.exe`
- Download:
  `https://github.com/jmb-sagiwork/Sagi-SmartAdvisor/raw/refs/heads/main/release/BillSearchControlPrinter-0.1.2-x64.exe`
- SHA-256:
  `68402f32c263b2af70f522831c2dc94f4a6ad6e4bbd987fae0d754faa0c9704c`
- PE architecture: x64 (`0x8664`)
- Validation: 81 tests passed

## Achievements

### Reliable Open Bill launch

The original toolbar/MSAA action did not activate Open Bill reliably. The
workflow now:

1. Finds the exact `SmartAdvisor Main System` window.
2. Sends `Ctrl+O` once.
3. Waits for this hierarchy:

   ```text
   frmBillOpen
   └─ Frame1 / Enter Bill To Edit
      └─ _cmdSearch_1
   ```

4. Uses a real `click_input()` on `_cmdSearch_1` as the primary action.
5. Waits briefly for the next search control.
6. Uses UIA InvokePattern only if the real click fails or produces no result.

Important: pywinauto UIA `.click()` commonly routes through InvokePattern, so
`click_input()` is the meaningfully different physical-click path.

### Stable Bill Search hierarchy

After `_cmdSearch_1`, the workflow finds:

```text
frmBillSearch / Bill Search
└─ Frame1 / Bill Records
```

The driver reacquires this existing hierarchy for each scoped control. It does
not reopen or restart Bill Search.

The current stable sequence is:

```text
_cmdSearch_1       → real click, InvokePattern fallback
txtClient          → clear existing client text
btnAdvacedSearch   → click Advanced Search
txtClaimID         → enter claim number
txtDOSFrom         → enter DOS From
cmdOK              → confirm/open selected result
263910             → subsequent click
198916             → read Patient Account
329468             → read/click charge amount
1901400            → close result window
```

The Bill Records-scoped controls are:

- `txtClient`
- `btnAdvacedSearch`
- `txtClaimID`
- `txtDOSFrom`

### Stable selectors replaced changing numeric IDs

Several numeric WinForms AutomationIds changed between runs and were replaced:

| Purpose | Removed unstable ID | Current stable ID |
|---|---:|---|
| Client text | `394450` | `txtClient` |
| Claim ID | `197684` (previously also `67390`) | `txtClaimID` |
| DOS From | `67512` | `txtDOSFrom` |

`txtClient` is cleared with `set_edit_text("")` through its editable UIA
ValuePattern. If that fails, the fallback focuses it, clicks it, and sends
`Ctrl+A` followed by Backspace.

Claim ID and DOS use `set_edit_text(value)` with mouse/keyboard input fallback.

### Release history from this conversation

- 0.3.2: switched Open Bill launch back to `Ctrl+O` and targeted
  `_cmdSearch_1` with InvokePattern.
- 0.3.3: made real `click_input()` primary for `_cmdSearch_1`, with
  InvokePattern fallback.
- 0.3.4: added exact Bill Search/Bill Records scoping and the first corrected
  search-field selectors.
- 0.3.5: replaced changing numeric IDs with `txtClient`, `txtClaimID`, and
  `txtDOSFrom`.

### Bill Search control-tree diagnostic

A separate console utility was created to run
`print_control_identifiers()` against the open Bill Search window:

```text
BillSearchControlPrinter-0.1.0-x64.exe
BillSearchControlPrinter-0.1.1-x64.exe
BillSearchControlPrinter-0.1.2-x64.exe
```

Findings and fixes:

1. Version 0.1.0 tried to connect to `Bill Search` as a top-level window and
   failed because it is nested under `SmartAdvisor Main System` and
   `Open Bill`.
2. Version 0.1.1 connected to `SmartAdvisor Main System`, but waited for the
   parent to be `enabled`. This timed out because the modal Bill Search dialog
   disables its parent.
3. Version 0.1.2 reuses SmartAdvisorAutomation's proven
   `find_smartadvisor_window("uia")` attachment logic. It does not require the
   disabled parent to be enabled.
4. `descendants()` returns wrapper objects, which do not provide
   `wait()` or `print_control_identifiers()`. Version 0.1.2 therefore reopens
   the matched Bill Search native handle as a WindowSpecification before
   printing the control tree.

The generated control tree is saved in `result.txt`.

## Resolved: candidate row iteration (0.4.0, not yet built)

The unreadable grid is no longer blocking. Rows are walked by keyboard and each
candidate is opened and read. **Every candidate re-runs the entire flow from
`Ctrl+O`** — nothing is reused between candidates, which is what removes the
need to close a bill and return to a still-populated grid.

Per candidate (row index `i`, zero-based):

```text
Ctrl+O → _cmdSearch_1 → clear txtClient → btnAdvacedSearch
→ txtClaimID → txtDOSFrom → cmdOK        (Bill Search OK: runs the search)
→ click inside fpSearchResult            (focus; arrow keys need real focus)
→ {DOWN}×1 {UP}×1                        CALIBRATION to the topmost row
→ {DOWN}×i                               seek to row i
→ {ENTER}                                confirm the row
→ cmdOk                                  Open Bill OK: opens frmBillEntry
→ radButton1                             only if the pended-bill warning shows
→ select Lines tab on Tab1                accelerator, then strip click +
                                          {RIGHT}, then ^{TAB}; verified by Name
→ read _lblTotals_59                     first plain value only
→ title bar Close on frmBillEntry, i += 1
```

Matching is on **charge amount only**. There is **no row cap**: the loop stops
when the amount repeats, which is what happens once the seek clamps at the last
row. Cancel is the operator's stop control, checked once per iteration.

### Newly confirmed selectors

| Purpose | Selector | Note |
|---|---|---|
| Run search | `cmdOK` | Bill Search dialog |
| Open selected bill | `cmdOk` | Open Bill window — **differs only by case** |
| Pended warning OK | `radButton1` + Name `&OK` | Generic Telerik id, so Name is required too |
| Bill window | `frmBillEntry` | Non-modal; Name embeds bill number and DCN, so never match on Name |
| Lines charge amount | `_lblTotals_59` | Control-array id; holds a plain value and a parenthesised one |
| Close bill | Name `Close`, ControlType `Button` | **No AutomationId** — non-client title bar element |

Retired: `263910`, `198916`, `329468`, `1901400`.

### Things that bit, recorded so they do not repeat

- `cmdOK` and `cmdOk` are two different buttons in two different windows.
  Matching is exact (`selector_match_strategy`), so they cannot collide at
  runtime, but they transpose trivially by hand. `test_selectors.py` guards it.
- The old `extract_amount` required a literal `$`. The Lines totals have none,
  so it silently returned the whole label. It now takes the text before the
  first `(` and parses that.
- `{DOWN}` then `{UP}` is **calibration, not seeking**. Folding it into the row
  count moves every candidate down by one.
- The title bar Close button has no AutomationId, so `ControlSpec` gained
  optional `name`/`control_type`, and `scope_automation_id` to confine the
  search — unscoped, every window's Close button matches.
- The bill's tab control (`Tab1`) publishes **only the selected page** in the
  UIA tree, so the Lines controls do not exist at all until Lines is selected.
  Its `Name` is the selected page's text (`"  Hea&der"`, `" &Lines(10)"`),
  which is what makes a switch verifiable.
- **Reaching the Lines tab is still not settled**, and two builds guessed
  wrong. 0.4.0 sent `%l` to `frmBillEntry` and Header stayed selected. 0.4.1
  replaced that with `{RIGHT}` and the Name never changed either. 0.4.2 stops
  guessing: it tries the accelerator, then a strip click plus `{RIGHT}`, then
  `^{TAB}`, verifying by Name after each and logging which one worked.
- Two facts checked against the installed pywinauto 0.6.9 rather than assumed:
  - `window_text()` is **not** cached. It returns `element_info.rich_text`;
    `cache_enable` defaults to `False`, so the Name is read live from
    `CurrentName` each call. A repeated Name means the tab really did not move.
  - `TabControlWrapper.select()` is **unusable here**. `UIAWrapper._select`
    needs `children(title=...)` to expose SelectionItem, and this control's
    only child is the page pane — there are no TabItem children.
- The Name needs time to repaint after a keystroke, and over Citrix that is
  not instant. Reading it immediately made a working keystroke look inert, so
  each attempt now polls for up to `BILL_TAB_SETTLE_TIMEOUT`.
- `^{TAB}` is the last resort deliberately: `frmBillEntry` sits inside an MDI
  parent, where Ctrl+Tab can switch child windows rather than tab pages.
- The tab and pane names carry the line count (`Lines(10)`), so they still
  cannot be used as selectors — only as a substring check.
- Resolving an unscoped selector took **27 seconds** live, because
  `_all_elements` walked every process window's full descendant tree on every
  poll. Containers are now cached per candidate row (`invalidate_scopes()`)
  and looked up with `descendants(depth=SCOPE_SEARCH_DEPTH)`.

### Still open

Patient Account has no selector in this flow. `WorkflowResult.patient_account`
is `str | None` and reports blank. Populating it needs one capture from the
bill's Header tab.

### UI log panel

The app now has a Log panel with Copy / Save / Clear, fed by both the workflow
and driver. It records selector metadata, step outcomes and amount **shapes**
(`#,###.##`) only — never claim ids, dates, accounts or amount values. Saved
logs land in `%LOCALAPPDATA%\SmartAdvisorAutomation\diagnostics\`.

## Historical: why the search-results grid is unreadable

After searching, SmartAdvisor shows a custom results grid:

```text
AutomationId: fpSearchResult
ControlType: Pane
Framework: WinForm
Parent: Frame1 / Bill Records
Window: frmBillSearch / Bill Search
```

It is likely an owner-drawn FarPoint Spread-style control.

### UIA findings

- No GridPattern
- No TablePattern
- No TextPattern
- No ValuePattern
- No SelectionPattern
- No ItemContainerPattern
- No row, cell, or header children
- The only anonymous child pane leads to scrollbars, not grid data

Therefore rows and columns cannot be read using normal AutomationId selectors.
This is not a missing selector; the control does not publish cell semantics.

`result.txt` confirms the stable hierarchy and selector:

```text
frmBillSearch / Bill Search
└─ Frame1 / Bill Records
   └─ fpSearchResult / Pane
```

The exact pywinauto selector is:

```python
results = bill_search.child_window(
    auto_id="Frame1",
    control_type="Group",
).child_window(
    auto_id="fpSearchResult",
    control_type="Pane",
)
```

The two children shown beneath `fpSearchResult` use changing numeric
AutomationIds and represent scrollbar panes, not data rows or cells. There are
no hidden stable AutomationIds for individual rows, columns, or cells.

### Clipboard and keyboard findings

- `Ctrl+A`, `Ctrl+C`, and pasting into Notepad do not expose the table.
- Keyboard row movement works only after focus is inside `fpSearchResult`.
- The selected/focused row moves with keyboard navigation.
- Right Arrow does not navigate readable cells as expected and interacts with
  the scrollbar.

### MSAA findings

MSAA exposes the grid only as a client object:

```text
Role: client
State: focused, focusable
ChildCount: 2
Description: "fpSearchResult, Sheet1, Row 0, Column 0, P"
```

The two children are the scrollbars. The MSAA Description remains static when
the selected row moves, so it cannot be used to read cell contents or identify
the selected row.

### Business requirement

There can be multiple result rows. The automation must inspect several values,
including charge amount, to determine which row is correct. Always choosing the
first row is not sufficient.

## Recommended next approach

Direct accessibility-based table reading is exhausted. Two realistic paths
remain.

### Preferred: open and validate candidates

Avoid reading the owner-drawn grid. Instead:

```text
Focus fpSearchResult
→ select a candidate row with the keyboard
→ click cmdOK or press Enter
→ open the candidate details
→ read accessible fields such as charge amount
→ compare all required criteria
```

On mismatch:

```text
Close candidate details without changing data
→ return to Bill Search
→ refocus fpSearchResult
→ move Down to the next row
→ open and validate again
```

This is preferable to OCR if opening and returning are safe because the
existing workflow already reads Patient Account and charge amount after a
result is opened.

Questions that still need answers before implementation:

1. Does `cmdOK` or Enter open the currently selected result?
2. Can the candidate details be closed and return safely to the same Bill
   Search results?
3. Which fields must match besides charge amount?
4. Are those fields available in the opened detail window, and what are their
   AutomationIds?
5. Approximately how many candidate rows can appear?
6. Does the selected row remain selected after returning, or should each
   iteration start at the first row and press Down a known number of times?

A safe maximum candidate count and a no-change screenshot check can prevent an
infinite loop when the final row is reached.

### Fallback: OCR the grid

If candidate details cannot be opened and closed safely, capture only the
`fpSearchResult` rectangle and OCR its visible rows and columns. This requires:

- a redacted screenshot showing headers and several rows;
- the charge-amount column and all other matching columns;
- Citrix resolution and display-scaling details;
- expected formatting for each value.

OCR is less desirable because it is sensitive to scaling, font rendering,
column widths, scrolling, and selection highlighting.

The untracked `try` file is an early OCR/typing experiment using `pyautogui`,
`pytesseract`, and a fixed screen region. It is not integrated with
SmartAdvisorAutomation and should be treated as reference-only.

## Safety and privacy

- The automation is attended and runs inside the authenticated Citrix session.
- Claim ID, DOS, Patient Account, and Amount must not be written to logs.
- Diagnostic reports should contain selector/control metadata only.
- No SmartAdvisor login automation is included.
- Candidate inspection must be read-only until the correct row is confirmed.
