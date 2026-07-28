# SmartAdvisor Automation

This repository contains an attended Windows automation for SmartAdvisor's
**No Bill on File** workflow.

The application runs inside the same Citrix Windows session as an already
authenticated SmartAdvisor instance. The user enters a Claim ID and DOS From,
then the bot performs the supplied SmartAdvisor steps, reads Patient Account
and Amount, closes the result window, and displays the result in Tkinter.

## Automated workflow

1. Click `cboClient`.
2. Click `_cmdSearch_1`.
3. Click `263892`, select all text, and clear it.
4. Click `btnAdvacedSearch`.
5. Enter Claim ID in `67390`.
6. Enter DOS From in `67512`.
7. Click `cmdOK`.
8. Click `263910`.
9. Read Patient Account from `198916`.
10. Read Amount from `329468`, then click that control as specified.
11. Click `1901400` to close the result window.

The application never stores Claim ID, DOS, Patient Account, or Amount on
disk. It does not handle SmartAdvisor authentication.

SmartAdvisor detection uses the dynamic native window handle for the exact
32-bit WinForms identity:

- title: `SmartAdvisor Main System`;
- class prefix: `WindowsForms10.Window.`.

The HWND and process ID are discovered at runtime and are never hard-coded.
Attachment then follows the stable parent hierarchy:
`Open Bill` window → `Frame1` / `Enter Bill To Edit` group → `cboClient`.

The attach probe searches visible top-level windows owned by the discovered
SmartAdvisor process and selects exact UIA `AutomationId=frmBillOpen`. It then
walks direct UIA children to `AutomationId=Frame1` and verifies the direct
`AutomationId=cboClient` ComboBox before attaching. HWND values remain dynamic.

## Object extractor

Use `SmartAdvisorObjectExtractor-0.1.0-x86.exe` when the automation cannot
reach a parent or control. It is a separate read-only diagnostic utility that:

- discovers SmartAdvisor without requiring the `Frame1` handshake;
- walks native HWND, UIA, and Win32 trees one node at a time;
- records parent relationships and per-node traversal failures;
- saves a JSON report selected through a Save dialog;
- excludes field values and redacts every unknown control name.

Open SmartAdvisor and the **Open Bill** window before extracting. Send the
saved `SmartAdvisor-object-report.json` back for selector diagnosis.

## Control picker

Use `SmartAdvisorControlPicker-0.2.0-x86.exe` when a control's
`AutomationId` is unknown or a guess turned out wrong. Starting from the
SmartAdvisor main window, it highlights one child at a time on screen and
asks: **No** (next sibling), **Yes** (right branch, but a container - dig
into its children), or **Final** (this exact control - stop here). It never
clicks, types, or submits anything in SmartAdvisor; it only highlights and
asks.

Select **Record a control** once per control you need. Each confirmed
control is held in the session together with the full ancestor path walked
to reach it, so three controls produce one `entries` array in a single
report instead of three separate files. **Save recording** writes them all
at once; **Discard all** clears the session. A stopped walk keeps whatever
was already recorded. Send the report back so the real `AutomationId` and
its parent chain can replace a guess in `selectors.py`.

## Action recorder

Use `SmartAdvisorActionRecorder-0.1.0-x86.exe` to capture a whole workflow
instead of one control at a time. Select **Start recording**, work through
SmartAdvisor by hand, select **Stop recording**, then save one JSON file.

Each step records the action (`click`, `input`, `key`), the target's
`AutomationId`, its ancestor path and owning window, the delay since the
previous step, and how many visible enabled controls shared that
`AutomationId` at the time - so a step that would fail the driver's
exactly-one-match rule is flagged as `[AMBIGUOUS]` before any code is
written. Steps with no `AutomationId` are flagged `[NO ID]`.

**Typed characters are never captured.** A text entry is recorded only as
"this control received typing"; the value comes from a run parameter, the
way `claim_id` and `dos_from` already do. Keyboard shortcuts such as
`Ctrl+O` and structural keys such as `{TAB}`/`{ENTER}` *are* recorded,
since they are part of the workflow and carry no data.

The recorder observes input and passes every event straight through - it
never clicks or types in SmartAdvisor. Note that it installs a low-level
Windows input hook, which endpoint security tooling may flag on an
unsigned executable; clear it with whoever owns endpoint policy before
deploying it into a managed Citrix estate.

## Run from source

```powershell
python -m pip install -e ".[dev]"
python -m smartadvisor_automation
```

Before running:

1. Open Citrix.
2. Sign in to SmartAdvisor manually.
3. Leave the **Open Bill** window on screen with the
   **Enter Bill To Edit** group and `cboClient` available.
4. Start the automation inside the same Citrix session.
5. Enter Claim ID and DOS From.
6. Select **Run workflow**.

Use **Validate controls** when troubleshooting. Validation is read-only and
reports only how many known selectors are visible; it does not run the
workflow.

## Build

```powershell
.\scripts\build.ps1
```

The build creates:

```text
dist\SmartAdvisorAutomation-0.3.0-x86.zip
release\SmartAdvisorAutomation-0.3.0-x86.exe
release\SmartAdvisorObjectExtractor-0.1.0-x86.exe
release\SmartAdvisorControlPicker-0.2.0-x86.exe
release\SmartAdvisorActionRecorder-0.1.0-x86.exe
```

The ZIP contains the supported one-folder package. The standalone EXE is
committed for direct download and may start more slowly because it extracts
its runtime to a temporary directory.

The committed release is built with 32-bit Python to match the 32-bit
SmartAdvisor WinForms process. GitHub Actions verifies that the executable's PE
machine type is `0x014c` (x86) before publishing the artifact.

## Test

```powershell
python -m pytest
```

## Safety

- The user signs in before the automation starts.
- Inputs and extracted values remain in memory only.
- Progress and errors use step numbers, not claim or patient data.
- A selector must match exactly one visible control before any action occurs.
- Cancellation is checked between steps.
- No Save, Submit, Update, or Delete control is used by this workflow.
