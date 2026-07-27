# SmartAdvisor Citrix Automation Pipeline

> **Document status:** Sections 1–8 preserve the original design plan.
> Section 9 onward is the authoritative implementation and troubleshooting
> record as of July 25, 2026. Future work should start with Sections 9–17.

## 1. Objective

Build an attended, read-only Windows automation assistant for SmartAdvisor. The
assistant runs inside the same Citrix Windows session as SmartAdvisor, accepts
one claim or case ID through a Tkinter UI, searches for the corresponding
record, extracts an approved fixed set of fields, and presents a structured
result to the user.

The first release must not create, update, submit, or delete SmartAdvisor data.

## 2. Confirmed Constraints

- **Runtime:** The executable runs inside the Citrix session and bundles a
  32-bit Python runtime; Python does not need to be installed in Citrix.
- **Delivery:** Packaged Windows executable; end users do not install Python or
  dependencies.
- **UI:** Tkinter.
- **Primary automation driver:** `pywinauto`.
- **Fallback driver:** `pyautogui` with anchored image matching and OCR only
  when a required control is not exposed through Windows automation.
- **Authentication:** The user launches Citrix, opens SmartAdvisor, and signs in
  before starting the assistant.
- **Operating mode:** Attended and user-supervised.
- **Input:** One manually entered claim or case ID.
- **Output:** A fixed, approved set of fields displayed in the assistant.
- **Data access:** Read-only.

## 3. Architecture

### Tkinter application

The interface contains:

- SmartAdvisor connection status.
- Claim or case ID input.
- Search, Cancel, Copy Result, and Clear actions.
- A structured result area.
- A concise progress and error message area.

The Search action is disabled until an authenticated SmartAdvisor window is
detected. UI updates from the automation worker must be passed back to
Tkinter's main thread through a thread-safe queue.

### Session adapter

The adapter finds and attaches to the authenticated SmartAdvisor process and
top-level window. It must verify the window title, process identity, and
expected landmark controls before each search. It must never launch or fill the
SmartAdvisor login screen.

### Control adapter

Control discovery tests both `win32` and `uia` backends from inside Citrix. The
backend that exposes the most stable and actionable controls becomes the
default. Selectors are stored in a central registry and prefer:

1. Automation ID plus control type.
2. Stable title plus control type and parent hierarchy.
3. Stable class name and parent hierarchy.
4. Relative position from a verified visual anchor as a final fallback.

Absolute screen coordinates must not be the primary selector strategy.

### Workflow service

The workflow service validates the input, attaches to SmartAdvisor, performs
the search, classifies the result, extracts the configured fields, and returns
a typed result to the Tkinter layer. It owns retry, timeout, cancellation, and
window-state recovery behavior.

### Result model

Every lookup returns:

- Input claim or case ID.
- Status: `complete`, `not_found`, `multiple_matches`, `cancelled`, or `failed`.
- Extracted fixed fields when the status is `complete`.
- A user-safe message.
- Start and completion timestamps.
- A diagnostic correlation ID that contains no claim or customer data.

The exact extracted field names remain an implementation gate and must be
approved before the lookup workflow is built.

## 4. Delivery Pipeline

### Stage 1 — Control discovery

**Entry condition:** SmartAdvisor is open and authenticated in a non-production
or approved test Citrix session.

1. Run a discovery build inside Citrix.
2. Enumerate top-level windows and descendants with both `win32` and `uia`.
3. Record control types, titles, automation IDs, class names, parent paths, and
   supported interaction patterns.
4. Identify stable landmarks for the main window, search screen, result screen,
   and result-state messages.
5. Redact or omit live claim and customer values from discovery output.
6. Delete temporary screenshots after selector review.

**Output:** A reviewed selector registry and selected primary backend.

**Gate:** The search input, search action, result container, and required output
fields must be addressable through stable selectors or approved visual anchors.

### Stage 2 — Workflow definition

Document one complete manual lookup using a dummy or approved test record:

1. Starting SmartAdvisor window and menu location.
2. Navigation sequence to the search screen.
3. Claim or case ID entry.
4. Search submission.
5. Indicator for a single matching record.
6. Indicator for no records.
7. Indicator for multiple records.
8. Location and format of every required output field.
9. Navigation required to return to a known starting state.

**Output:** An approved workflow map, fixed extraction field list, and result
classification rules.

**Gate:** No lookup implementation begins until all three result states and the
fixed field list are defined.

### Stage 3 — Lookup implementation

1. Attach to the existing authenticated SmartAdvisor session.
2. Validate the claim or case ID format without logging its value.
3. Navigate from a verified landmark to the search screen.
4. Clear stale search values before entering the new ID.
5. Submit the search once.
6. Wait for an explicit success, not-found, multiple-match, or timeout signal.
7. Extract fixed fields only after a single record is confirmed.
8. Normalize whitespace and preserve displayed identifiers and dates as text.
9. Return SmartAdvisor to the documented safe starting state when possible.
10. Display the structured result without writing data back to SmartAdvisor.

**Output:** A working single-record, read-only lookup.

### Stage 4 — Reliability and safety

- Use explicit condition-based waits instead of fixed sleeps.
- Apply per-step timeouts and one bounded retry for transient focus or timing
  failures.
- Before a retry, revalidate the active window and landmark control.
- Never retry a search blindly if SmartAdvisor may still be processing it.
- Support cooperative cancellation between steps; do not interrupt midway
  through a UI action.
- Pause and prompt the user when the session is locked, expired, disconnected,
  or displaying an unexpected modal dialog.
- Fail closed when selectors do not match the expected screen.
- Do not click Save, Submit, Update, Delete, or equivalent actions.

### Stage 5 — Packaging

1. Pin Python and dependency versions in the build environment.
2. Package the user-facing release with PyInstaller in **one-file** mode. This
   is an explicit project requirement because Citrix may not have Python and
   the user does not want to transfer an `_internal` directory.
3. Include only approved selector assets and OCR resources.
4. Store runtime configuration beside the executable in a read-only default
   configuration file.
5. Write logs to an approved per-user location with rotation and retention
   limits.
6. Generate a version manifest containing application version, build date,
   dependency versions, and selector-registry version.
7. Submit the package for required security scanning, code signing, and Citrix
   deployment approval.

**Output:** A versioned, approved deployment bundle.

### Stage 6 — Citrix validation

Test with the same display scaling, resolution policy, SmartAdvisor version,
permissions, and session configuration used by production users.

Required scenarios:

- SmartAdvisor is open, authenticated, and ready.
- SmartAdvisor is not open.
- SmartAdvisor is open but logged out.
- Valid ID with one result.
- Valid ID with no result.
- Valid ID with multiple results.
- Empty or malformed input.
- Slow search response.
- Unexpected modal dialog.
- User cancels before submission.
- User cancels while waiting for results.
- Citrix disconnects or locks.
- SmartAdvisor moves, resizes, or temporarily loses focus.
- A required field is blank.
- A required selector changes.

### Stage 7 — Supervised pilot

1. Start with non-sensitive or approved test records.
2. Compare every extracted field with a manual lookup.
3. Record selector failures and timing issues without recording customer data.
4. Promote only after the agreed sample has no incorrect record matches and no
   unintended SmartAdvisor writes.
5. Keep the first production release attended and single-record only.

## 5. Runtime State Machine

The UI and workflow use these states:

- `ready` — SmartAdvisor is detected and the user may enter an ID.
- `attaching` — validating process, window, and landmark controls.
- `searching` — navigating, entering the ID, and awaiting a result.
- `extracting` — reading the approved fixed fields.
- `complete` — one record was found and extracted.
- `not_found` — SmartAdvisor explicitly reported no match.
- `multiple_matches` — more than one record requires user resolution.
- `session_expired` — authentication is no longer valid.
- `cancelled` — the user stopped the operation safely.
- `failed` — the expected screen or control could not be verified.

Each transition must be triggered by an observable condition rather than a
blind delay.

## 6. Logging and Data Protection

- Never log credentials.
- Never log claim or case IDs, names, addresses, notes, or extracted field
  values.
- Log timestamps, application version, workflow step, selector name, duration,
  outcome, and a random correlation ID.
- Redact window titles or control text when they may contain customer data.
- Screenshots are off by default. Diagnostic screenshots require explicit user
  action, must be cropped to the relevant application area, and must be deleted
  after review.
- Apply an approved retention period and restrict log access to the current
  user and support personnel.

## 7. Acceptance Criteria

The first release is accepted only when:

- The packaged EXE starts inside the approved Citrix environment without a
  local Python installation.
- It attaches only to an already authenticated SmartAdvisor session.
- A user can enter one claim or case ID and receive the approved fixed fields.
- Single-result, not-found, and multiple-match outcomes are distinguished
  reliably.
- No test causes a SmartAdvisor record to be created, modified, submitted, or
  deleted.
- Selector failures stop safely and provide a useful redacted diagnostic.
- Cancellation leaves SmartAdvisor in a known or clearly reported state.
- Logs contain no credentials or customer/claim data.
- Extracted values match manual verification for the approved pilot sample.

## 8. Open Discovery Inputs

These facts must be supplied or captured during Stages 1 and 2:

- Exact menu and control sequence for a manual lookup.
- Exact fixed field names to extract.
- Visual or control indicators for one result, no result, and multiple results.
- SmartAdvisor executable/process identity inside Citrix.
- Whether `win32`, `uia`, or a hybrid backend is most stable.
- Citrix display scaling and resolution policy.
- Required packaging, signing, deployment, and log-retention approvals.

## 9. Current Implementation Snapshot

This section supersedes conflicting assumptions in the original plan.

- Repository:
  `https://github.com/jmb-sagiwork/Sagi-SmartAdvisor`
- Branch: `main`
- Platform: Windows desktop application running inside Citrix.
- Target application: 32-bit SmartAdvisor WinForms.
- Automation UI: Tkinter.
- Automation library: `pywinauto==0.6.9`.
- Packager: PyInstaller one-file executable.
- Required build architecture: x86 (`PE machine 0x014C`).
- Current workflow executable:
  `release/SmartAdvisorAutomation-0.2.5-x86.exe`.
- Current diagnostic executable:
  `release/SmartAdvisorObjectExtractor-0.1.0-x86.exe`.
- Current automated test count: 37 passing.
- No Python installation is required in Citrix.
- The executable must run inside the same Citrix Windows session as
  SmartAdvisor.
- SmartAdvisor and the automation should run at the same elevation level. If
  SmartAdvisor is elevated, the automation must also be elevated.

The current implementation is an attended **No Bill on File** workflow. It
does not use `pyautogui` or coordinate clicking as its primary mechanism.
Visual automation remains only a possible future fallback.

## 10. Implemented Workflow and Selectors

The supplied manual workflow was translated into the following stable selector
sequence. Live claim IDs, dates, patient accounts, and amounts are deliberately
not repeated in this document.

| Step | Automation ID | Purpose | Action |
|---|---|---|---|
| 1 | `cboClient` | Open bill/client selection | Click |
| 2 | `_cmdSearch_1` | Additional search options (`...`) | Click |
| 3 | `263892` | Search/input box | Click, select all, clear |
| 4 | `btnAdvacedSearch` | Advanced Search | Click |
| 5 | `67390` | Claim ID | Input |
| 6 | `67512` | DOS From | Input |
| 7 | `cmdOK` | Confirm search | Click |
| 8.1 | `263910` | Verify/select claim details | Click |
| 8.2 | `198916` | Patient Account | Read |
| 8.3 | `329468` | Amount | Read, then click |
| 9 | `1901400` | Close result/message window | Click |

Selector rules:

1. Match an exact `AutomationId` first.
2. If the supplied selector is numeric, permit an exact numeric Win32
   `control_id` match.
3. Require exactly one visible and enabled match before acting.
4. Never hard-code runtime HWNDs or process IDs.
5. Never log the values entered at steps 5–6 or extracted at steps 8.2–8.3.

## 11. Troubleshooting Timeline

### 11.1 Initial visibility limitation

Codex cannot directly see or control the user's local or Citrix desktop from
the repository environment. Any discovery tool must be run by the user inside
the same Citrix session as SmartAdvisor. The user must return redacted
inspection output or a generated diagnostic report.

### 11.2 First executable behavior

The first executable was intended to:

1. provide a Tkinter form for Claim ID and DOS From;
2. attach to an already authenticated SmartAdvisor session;
3. run the supplied selector sequence;
4. display the Patient Account, Amount, and fixed outcome message;
5. avoid requiring Python in Citrix.

The initial ZIP also contained an `_internal` directory. That was the normal
PyInstaller one-folder runtime, not source code and not an indication that
Python had to be installed. The user explicitly preferred a single EXE, so the
release pipeline was changed to publish a PyInstaller one-file executable.

### 11.3 Main SmartAdvisor window was not detected

The initial application detector did not reliably find SmartAdvisor. Inspect
output supplied by the user established the top-level identity:

- visible title: `SmartAdvisor Main System`;
- class prefix: `WindowsForms10.Window.`;
- application type: 32-bit WinForms;
- observed UIA process ID: `29524`;
- observed provider proxy process ID: `38648`;
- observed sample HWND: `0x000409E0`.

The IDs and HWND above are evidence from one run only. They are dynamic and
must never be used as selectors.

The title bar itself appeared as a UIA TitleBar element with a parent
`SmartAdvisor Main System` window. Citrix/UIA provider descriptions showed
proxying between process IDs, which is one reason title-only UIA discovery was
not sufficient.

Fix implemented in commit `bc745c8`:

- enumerate visible native top-level HWNDs;
- match the exact title and WinForms class prefix;
- choose the foreground match when available, otherwise the largest matching
  window;
- wrap the selected dynamic HWND using the requested `uia` or `win32`
  backend;
- retain strict UIA desktop enumeration only as a fallback.

### 11.4 Main window found, but controls were inaccessible

After main-window detection was fixed, the x64 executable found SmartAdvisor
but returned:

```text
smartadvisor_controls_not_accessible
```

The key diagnosis was an architecture mismatch:

- SmartAdvisor: 32-bit WinForms;
- packaged automation at that time: 64-bit Python/PyInstaller.

Matching the target architecture matters for legacy WinForms and Win32
control inspection. The build pipeline was therefore changed to use 32-bit
Python 3.11 in GitHub Actions and to verify the PE machine type before
publishing.

Build work:

- `285c19b` — add x86 executable pipeline;
- GitHub Actions run `30119731246` — successful x86 build;
- `f2df291` — publish `SmartAdvisorAutomation-0.2.2-x86.exe`.

The published 0.2.2 executable was verified as:

- PE machine: `0x014C`;
- size: `11,899,606` bytes;
- SHA-256:
  `AAC5BE74A76A0DBD10758D004BCC3AF634B5562584B7D279471A937E3E88FAF5`;
- startup smoke test: remained running for eight seconds and left no test
  process behind;
- tests at that point: 25 passing.

This corrected the architecture mismatch but did not fully solve descendant
access in Citrix.

### 11.5 Parent of `cboClient` identified

The user navigated upward from `cboClient` in Inspect.exe and supplied the
following stable parent:

- Control type: UIA Group;
- Name: `Enter Bill To Edit`;
- Automation ID: `Frame1`;
- Framework: `WinForm`;
- class prefix: `WindowsForms10.Window.`;
- observed native HWND: `0x00140866`;
- observed process ID: `29524`.

The observed child list was:

- `...` button;
- `...` button;
- `cboClient` combo box;
- `Read Only` check box;
- unnamed edit;
- `C&lient:` text;
- `Bill &Number:` text.

The observed UIA ancestor chain was:

```text
Frame1 / Enter Bill To Edit
└── Open Bill
    └── SmartAdvisor Main System
        └── Desktop 1
```

The sample HWND and process ID are diagnostic evidence only and are not
hard-coded.

### 11.6 Parent-scoped handshake implemented

Version 0.2.3 made the expected attach handshake explicit:

```text
SmartAdvisor Main System
└── Open Bill
    └── Frame1 / Enter Bill To Edit
        └── cboClient
```

Implementation details:

- locate `Open Bill` by exact native name and WinForms class beneath the main
  HWND;
- locate `Enter Bill To Edit` beneath `Open Bill`;
- validate the UIA group identity with exact `AutomationId=Frame1`;
- fall back to a narrow UIA traversal when native HWND nesting differs;
- resolve step 1 (`cboClient`) only inside the validated `Frame1` scope;
- resolve steps 2–9 across all visible SmartAdvisor process windows because
  later dialogs change;
- distinguish a missing parent with:
  `smartadvisor_open_bill_frame_not_accessible`.

Build work:

- `fa46243` — implement parent-scoped handshake;
- GitHub Actions run `30121671237` — successful x86 build;
- `387dd66` — publish `SmartAdvisorAutomation-0.2.3-x86.exe`.

The published 0.2.3 executable was verified as:

- PE machine: `0x014C`;
- size: `11,901,819` bytes;
- SHA-256:
  `BB30BE538E036A0F5A2A2FFFCA90DB98AE92EF4D3CE213F572A271FA04D85F25`;
- startup smoke test: remained running for eight seconds and left no test
  process behind;
- tests at that point: 29 passing.

### 11.7 Parent handshake still failed in Citrix

The user ran 0.2.3 with SmartAdvisor and Open Bill visible and received:

```text
smartadvisor_open_bill_frame_not_accessible
```

This error has a narrower meaning than the previous error:

1. `SmartAdvisor Main System` was found.
2. Neither backend completed the required `Open Bill` → `Frame1` handshake.
3. The workflow stopped before clicking `cboClient`.

The remaining hypotheses are:

- `Open Bill` is an owned top-level window rather than a native child of the
  main HWND;
- UIA displays `Open Bill` beneath the main window even though the native HWND
  parent/owner relationship differs;
- a Citrix/MSAA/UIA proxy branch throws while descendants are enumerated;
- the UIA element's reported process differs from the native provider process;
- the automation and SmartAdvisor are running at different elevation levels;
- the automation is running outside the exact Citrix desktop/session containing
  SmartAdvisor;
- the `win32` and `uia` backends expose different partial trees.

Do not guess another selector or add coordinates until an object report has
been captured.

### 11.8 Read-only object extractor created

Because the attach logic itself could not reach `Frame1`, a separate extractor
was created that does not depend on any workflow landmark.

Source work:

- `dd8c307` — add SmartAdvisor object extractor;
- GitHub Actions run `30123076540` — build and verify both x86 executables;
- `e8802f7` — publish
  `SmartAdvisorObjectExtractor-0.1.0-x86.exe`.

The extractor:

- locates the SmartAdvisor main HWND using the already verified exact
  title/class identity;
- identifies every top-level HWND owned by the SmartAdvisor process, so owned
  dialogs are not missed;
- extracts each native HWND tree;
- extracts separate UIA and Win32 trees for each process window;
- walks children node-by-node so one provider failure does not discard the
  rest of the tree;
- records `node_id`, `parent_id`, depth, automation ID, control ID, control
  type, class, framework, HWND, process ID, runtime ID, bounds, visibility,
  enabled state, truncation, and per-node error codes;
- never clicks, types, focuses, submits, or modifies SmartAdvisor;
- retains only the structural names `SmartAdvisor Main System`, `Open Bill`,
  and `Enter Bill To Edit`;
- marks every other UI name or native text as redacted;
- excludes field values and exception messages.

The published extractor was verified as:

- PE machine: `0x014C`;
- size: `11,936,008` bytes;
- SHA-256:
  `CBF28248C19069FE82DA690686D653B8CEC5E9FB66860170E70EFB3F430B787E`;
- startup smoke test: remained running for eight seconds and left no test
  process behind;
- current tests: 35 passing.

### 11.9 Object report analyzed and 0.2.4 fix implemented

The user returned `SmartAdvisorp_object_report_2.txt`. The extractor report was
valid, complete, and privacy-redacted.

Report summary:

- discovery status: `found`;
- matching SmartAdvisor main windows: 1;
- observed SmartAdvisor process ID: `23176`;
- process top-level windows: 12;
- native trees: 12, all `ok`;
- backend trees: 24 (12 UIA and 12 Win32), all `ok`;
- traversal errors: 0;
- truncated trees: 0.

The process ID and HWNDs below are evidence from that capture only and must
never be hard-coded.

The report proved that the native main and Open Bill windows are separate
top-level process roots:

- main root HWND `1510120`, UIA `AutomationId=bilMain`;
- Open Bill root HWND `1313322`, UIA `AutomationId=frmBillOpen`.

The clean UIA tree rooted directly at Open Bill was:

```text
Open Bill
AutomationId: frmBillOpen
ControlType: Window
HWND observed: 1313322
└── Enter Bill To Edit
    AutomationId: Frame1
    ControlType: Group
    HWND observed: 592642
    └── [redacted name]
        AutomationId: cboClient
        ControlType: ComboBox
        HWND observed: 854768
```

The same process tree was visible beneath the main UIA root, but native
enumeration treated Open Bill as its own top-level window. Native text did not
reliably expose `Enter Bill To Edit`. The Win32 backend exposed duplicate
representations of `cboClient`, while UIA exposed one clean parent chain.

This ruled out traversal permissions, provider crashes, and report truncation
for the captured session. It identified the remaining failure as resolver
strategy:

- matching Open Bill by text was weaker than its exact automation ID;
- wrapper-wide `descendants()` did not mirror the extractor's successful
  node-by-node traversal;
- native parent/name lookup could not represent the proven root boundary.

Version 0.2.4 therefore:

1. enumerates every visible top-level UIA window for the SmartAdvisor process;
2. requires exact `AutomationId=frmBillOpen`, name `Open Bill`, control type
   `Window`, and the WinForms class prefix;
3. reads only the Open Bill element's direct UIA children;
4. requires exactly one direct `AutomationId=Frame1`, name
   `Enter Bill To Edit`, control type `Group`;
5. reads only the Frame1 element's direct UIA children;
6. requires exactly one direct `AutomationId=cboClient`, control type
   `ComboBox`;
7. wraps the dynamically discovered `cboClient` HWND as the step-1 scope,
   avoiding another wrapper-wide descendant scan;
8. retains the earlier fallback only if the strict report-proven path does not
   resolve.

Regression coverage uses the exact process-root/direct-child hierarchy from
the report. No captured HWND or process ID is used in production selectors.

## 12. Error Code Reference

| Error code | Meaning | Immediate action |
|---|---|---|
| `smartadvisor_window_not_found` | Exact main title/class was not found | Confirm same Citrix session, visibility, and elevation |
| `smartadvisor_open_bill_frame_not_accessible` | Main window found, but `Open Bill`/`Frame1` handshake failed | Run the object extractor with Open Bill visible |
| `smartadvisor_controls_not_accessible` | Parent scope was found, but `cboClient` did not resolve uniquely/actionably | Inspect the extractor's `Frame1` children |
| `selector_not_found` | A later workflow selector was not found before timeout | Inspect the active dialog/root for that step |
| `selector_ambiguous` | More than one visible actionable control matched | Add a stable parent scope |
| `window_enumeration_failed` | Process windows could not be listed | Check backend, session, elevation, and provider errors |
| `not_attached` | An action was requested before a successful attach | Treat as an internal state failure |

All errors shown in the UI must remain safe: an error code and step number may
be displayed, but claim, patient, account, amount, and control values must not
be included.

## 13. Object Extractor Runbook

Download:

```text
https://github.com/jmb-sagiwork/Sagi-SmartAdvisor/raw/refs/heads/main/release/SmartAdvisorObjectExtractor-0.1.0-x86.exe
```

Before extraction:

1. Enter the Citrix desktop containing SmartAdvisor.
2. Sign in to SmartAdvisor manually.
3. Open the **Open Bill** window.
4. Leave **Enter Bill To Edit** and `cboClient` visible.
5. Run the extractor in the same session and at the same elevation level.

Extraction:

1. Select **Extract objects and save JSON**.
2. Save the default `SmartAdvisor-object-report.json`.
3. Attach that JSON to the development conversation.
4. Do not send screenshots or live field values unless separately approved.

The JSON is the next required diagnostic input. No further automation
selector changes should be made before reviewing it.

## 14. How to Analyze the Object Report

When a future session receives `SmartAdvisor-object-report.json`, analyze it in
this order:

1. Check `discovery.status`.
   - It must be `found`.
   - Record `selected_handle`, `process_id`, and `process_window_count`.
2. Review every entry in `native_trees`.
   - Find the allowlisted name `Open Bill`.
   - Determine whether its root is the main HWND or a separate process window.
   - Find `Enter Bill To Edit` and inspect its native `parent_id`.
3. Review `backend_trees` grouped by `backend` and `root_handle`.
   - Search exact `automation_id=Frame1`.
   - Search exact `automation_id=cboClient`.
   - Compare which root and backend exposes each one.
4. Review each tree's `status`, `truncated`, and `errors`.
   - A `partial` tree is useful; follow the error's `node_id`.
   - Determine the nearest successfully extracted parent.
5. Reconstruct the real path using `node_id` and `parent_id`.
6. Choose the smallest stable scope that contains both `Frame1` and
   `cboClient`.
7. Update the attach logic only after the actual backend/root relationship is
   proven.

Likely implementation directions after the report:

- attach to the separate `Open Bill` process-window HWND directly;
- search all SmartAdvisor process top-level windows before descendant search;
- resolve `Frame1` through UIA while retaining native HWND discovery;
- use a hybrid native-root/UIA-child adapter;
- if UIA consistently fails at a specific node, use the Win32 tree for that
  boundary and UIA below the next usable HWND.

Absolute coordinates remain a last resort.

### 14.1 July 25 object-report result

The returned extractor report completed without errors or truncation and found
the exact SmartAdvisor main window. It enumerated 47 process windows, but did
not expose `Open Bill`, `Frame1`, or `cboClient` in the captured native, UIA, or
Win32 trees.

The safe discovery expansion implemented from this evidence is to enumerate
all visible top-level windows owned by the discovered SmartAdvisor process
before searching the main-window descendant chain. Candidate `Open Bill`
windows still require the exact WinForms title/class identity, and an ambiguous
set is accepted only when exactly one candidate contains a valid `Frame1`.
Native descendant and UIA subtree fallbacks remain unchanged.

A future capture with `Open Bill`, `Enter Bill To Edit`, and `cboClient`
visible is still required to prove their actual backend/root relationship.
No selector, coordinate, hard-coded handle, or field-value logging was added.

## 15. Release and Commit Ledger

| Commit/run | Purpose |
|---|---|
| `8964102` | Add original automation pipeline |
| `d7da52f` | Add initial control discovery tool |
| `154c40e` | Add standalone discovery executable |
| `a782c82` | Implement No Bill on File workflow |
| `bc745c8` | Detect exact SmartAdvisor WinForms main window |
| `285c19b` | Add x86 executable pipeline |
| Actions `30119731246` | Build and PE-verify 0.2.2 x86 |
| `f2df291` | Publish 0.2.2 x86 executable |
| `fa46243` | Add `Open Bill` → `Frame1` handshake |
| Actions `30121671237` | Build and PE-verify 0.2.3 x86 |
| `387dd66` | Publish 0.2.3 x86 executable |
| `dd8c307` | Add privacy-safe object extractor |
| Actions `30123076540` | Build/verify automation and extractor x86 EXEs |
| `e8802f7` | Publish object extractor 0.1.0 x86 |

Current direct downloads:

```text
Automation:
https://github.com/jmb-sagiwork/Sagi-SmartAdvisor/raw/refs/heads/main/release/SmartAdvisorAutomation-0.2.3-x86.exe

Object extractor:
https://github.com/jmb-sagiwork/Sagi-SmartAdvisor/raw/refs/heads/main/release/SmartAdvisorObjectExtractor-0.1.0-x86.exe
```

## 16. Relevant Source Map

| File | Responsibility |
|---|---|
| `src/smartadvisor_automation/selectors.py` | Window identity, parent identity, and workflow selector registry |
| `src/smartadvisor_automation/probe.py` | Native main-window discovery, selector probing, and parent lookup |
| `src/smartadvisor_automation/driver.py` | Attach, scoped resolution, clicking, input, and extraction |
| `src/smartadvisor_automation/workflow.py` | Ordered No Bill on File workflow |
| `src/smartadvisor_automation/app.py` | Main Tkinter automation UI |
| `src/smartadvisor_automation/object_extractor.py` | Privacy-safe native/UIA/Win32 object extraction |
| `src/smartadvisor_automation/object_extractor_app.py` | Standalone extractor Tkinter UI and JSON save flow |
| `scripts/build.ps1` | PyInstaller build for both one-file EXEs |
| `.github/workflows/build-x86.yml` | 32-bit Python test/build/PE verification/artifact upload |
| `tests/test_driver.py` | Attach and scoped-resolution regression tests |
| `tests/test_probe.py` | Main-window and parent-identity regression tests |
| `tests/test_object_extractor.py` | Tree traversal, truncation, parent, and redaction tests |
| `tests/test_report_privacy.py` | Report schema privacy gates |
| `src/smartadvisor_automation/diagnostics.py` | Redacted step-by-step attach trace collector |

## 17. Current Handoff State

As of July 27, 2026:

- The exact SmartAdvisor main window is detected.
- The application and extractor are both genuine x86 executables.
- The workflow selector registry and ordered actions are implemented.
- The second object report proved the clean UIA chain
  `frmBillOpen` → `Frame1` → `cboClient`.
- Open Bill is a separate native top-level SmartAdvisor process root.
- UIA direct-child traversal completed without errors or truncation.
- Version 0.2.4 implements the exact process-root/direct-child hierarchy and
  verifies `cboClient` before attachment succeeds.
- Do not reintroduce x64 builds, hard-coded HWNDs/process IDs, raw field
  logging, or coordinate-first automation.

### 17.1 0.2.4 was never published, and still failed once it was

The 0.2.4 source and its Actions build (run `30129733119`) were complete on
July 24, but the built executable was only ever an Actions artifact — it was
never committed to `release/`. Every user run through July 27 was still the
pre-fix 0.2.3 build, so `smartadvisor_open_bill_frame_not_accessible`
recurring was expected and uninformative.

Commit `cd672fb` published the actual 0.2.4 artifact to
`release/SmartAdvisorAutomation-0.2.4-x86.exe`. The user then ran that
genuine 0.2.4 build with `Open Bill` open and received the **same**
`smartadvisor_open_bill_frame_not_accessible` error. This is unexplained by
the existing evidence: the July 24 object report proves the exact
`frmBillOpen` → `Frame1` → `cboClient` hierarchy that `_strict_uia_open_bill_frame`
is written to match. Re-analyzing that same static report cannot explain a
live failure of code the report itself validates — the report is stale
evidence, and guessing at another selector or fallback without new data
would repeat the same mistake.

### 17.2 Attach diagnostic trace added (0.2.5)

Rather than iterate on more static object-report captures, version 0.2.5 adds
a live, privacy-safe trace of the actual attach handshake:

- `smartadvisor_automation/diagnostics.py` defines `DiagnosticTrace`, a
  redacted step/backend/outcome log (match counts, exception class names —
  never titles, control text, or field values).
- `probe.py`'s resolution helpers (`find_smartadvisor_window`,
  `find_open_bill_frame`, `_strict_uia_open_bill_frame`,
  `_find_open_bill_process_window`, `_find_open_bill_in_main`,
  `_find_frame_in_open_bill`) each accept an optional `trace` and record
  exactly which strategy ran, what it matched or why it didn't, and any
  exception type raised.
- `driver.attach()` builds one `DiagnosticTrace` per attach attempt and
  attaches it to the raised `AutomationError` as `.diagnostics`.
- `app.py` writes that trace to
  `%LOCALAPPDATA%\SmartAdvisorAutomation\diagnostics\latest-attach-trace.json`
  on failure and shows the path in the error dialog.

**Next action:** run 0.2.5 with `Open Bill` open, reproduce the failure, and
send back `latest-attach-trace.json`. It will show which of the four
resolution strategies ran, the real match counts at each stage, and any
exception type — the first real evidence from a live failing attach, as
opposed to a three-day-old static snapshot.
