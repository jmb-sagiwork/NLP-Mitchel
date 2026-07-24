# No Bill on File Workflow

This is the implemented selector map for the first SmartAdvisor automation
workflow. Example claim, account, date, and amount values are intentionally
excluded from source control.

| Step | Automation ID | Purpose | Intended action |
| --- | --- | --- | --- |
| 1 | `cboClient` | Open bill/client selection | Click |
| 2 | `_cmdSearch_1` | Open additional search options | Click |
| 3 | `263892` | Search/input box | Focus and clear |
| 4 | `btnAdvacedSearch` | Open Advanced Search | Click |
| 5 | `67390` | Claim ID | Enter user-provided value |
| 6 | `67512` | DOS From | Enter user-provided date |
| 7 | `cmdOK` | Submit search criteria | Click |
| 8.1 | `263910` | Verify/select claim details | Click |
| 8.2 | `198916` | Patient Account | Extract displayed value |
| 8.3 | `329468` | Amount | Extract displayed value, then click |
| 9 | `1901400` | Close result/message window | Click |

## Implemented interpretation

- Step 3 means click, `Ctrl+A`, then Backspace.
- Step 8.1 clicks the supplied claim-detail selector.
- Step 8.2 reads Patient Account into the Tkinter result.
- Step 8.3 reads Amount and then clicks the supplied control.
- Step 9 closes the result/message window.
- DOS is normalized to `MM/DD/YYYY`.
- Claim ID accepts letters, numbers, dots, underscores, slashes, and hyphens.

The workflow stops safely when a selector is missing, duplicated, disabled, or
not visible. No customer values are written to logs or reports.

