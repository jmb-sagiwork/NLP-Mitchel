# SmartAdvisor Discovery

This repository contains the first milestone of the SmartAdvisor Citrix
automation project: a read-only Windows control validator.

The utility runs **inside the Citrix Windows session** alongside an already
authenticated SmartAdvisor instance. It tests the `uia` and `win32` pywinauto
backends against the known controls for the **No Bill on File** workflow.

It does not click controls, enter search values, extract field values, or modify
SmartAdvisor records.

## Run from source

```powershell
python -m pip install -e ".[dev]"
python -m smartadvisor_discovery
```

Before scanning:

1. Open Citrix.
2. Sign in to SmartAdvisor manually.
3. Navigate to the SmartAdvisor screen you want to validate.
4. Start the discovery utility inside that same Citrix session.
5. Select **Scan controls**.
6. Save the sanitized JSON report.

Repeat the scan on the main, search, single-result, not-found, and
multiple-result screens. Use dummy or approved test records even though the
report intentionally excludes field values and window text.

## Build the Citrix test package

```powershell
.\scripts\build.ps1
```

The executable is created at:

```text
dist\SmartAdvisorDiscovery\SmartAdvisorDiscovery.exe
```

PyInstaller uses one-folder mode. Transfer
`dist\SmartAdvisorDiscovery-0.1.0.zip` into the approved Citrix location,
extract it, and run `SmartAdvisorDiscovery.exe`. Do not copy the EXE by itself;
the adjacent runtime files are required.

## Test

```powershell
python -m pytest
```

## Data protection

The exported report contains selector metadata only:

- workflow step;
- automation ID;
- backend and matching strategy;
- control type and class name;
- visibility and enabled state;
- screen rectangle;
- sanitized error type.

It does not include SmartAdvisor window titles, control text, claim IDs,
patient accounts, dates of service, amounts, usernames, or credentials.
