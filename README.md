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

## Run from source

```powershell
python -m pip install -e ".[dev]"
python -m smartadvisor_automation
```

Before running:

1. Open Citrix.
2. Sign in to SmartAdvisor manually.
3. Leave SmartAdvisor on the screen where `cboClient` is available.
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
dist\SmartAdvisorAutomation-0.2.0.zip
release\SmartAdvisorAutomation-0.2.0.exe
```

The ZIP contains the supported one-folder package. The standalone EXE is
committed for direct download and may start more slowly because it extracts
its runtime to a temporary directory.

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

