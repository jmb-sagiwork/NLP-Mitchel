# SmartAdvisor Citrix Automation Pipeline

## 1. Objective

Build an attended, read-only Windows automation assistant for SmartAdvisor. The
assistant runs inside the same Citrix Windows session as SmartAdvisor, accepts
one claim or case ID through a Tkinter UI, searches for the corresponding
record, extracts an approved fixed set of fields, and presents a structured
result to the user.

The first release must not create, update, submit, or delete SmartAdvisor data.

## 2. Confirmed Constraints

- **Runtime:** Python inside the Citrix session.
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
2. Package with PyInstaller in **one-folder** mode for faster startup and easier
   inspection than a one-file executable.
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

