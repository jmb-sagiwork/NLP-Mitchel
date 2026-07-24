# No Bill on File Workflow

This is the sanitized selector map supplied for the first SmartAdvisor
automation workflow. Example claim, account, date, and amount values are
intentionally excluded.

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
| 8.3 | `329468` | Amount | Extract displayed value |
| 9 | `1901400` | Close result/message window | Click |

## Validation before action automation

The discovery utility must confirm which backend exposes each selector and
whether every selector is unique on its expected screen.

Before implementing clicks, the workflow owner must also confirm:

- whether step 3 means `Ctrl+A` followed by `Delete`;
- whether step 8.1 selects a result row or opens a details window;
- the exact indicator for no match and multiple matches;
- whether step 9 closes only the message/details window;
- the accepted Claim ID and DOS input formats.

