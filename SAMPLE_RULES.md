# Labelling rules derived from samples.xlsx

Fifteen real inbound emails, labelled by hand-written rule. Columns D-L in
`samples.xlsx` hold the answer a correct engine should produce; column M holds
the rule that produced each one. The executable version is
`scripts/label_samples.py` - that file, not this one, is the source of truth.

This page carries the findings that do not fit in a per-row cell.

---

## What the sample set actually contains

| | |
|---|---|
| Type of concern | **Bill Status 14 / 15**, Claim Information 1 / 15 |
| Reason stated | **blank 14 / 15**, "Claim number request" 1 / 15 |

Field fill rate, out of 15:

| Field | Found | Note |
|---|---|---|
| Claim ID | 14 | the one miss is the email *asking for* a claim number |
| DOS | 14 | |
| Prov TIN | 12 | |
| Expected Amount | 12 | |
| DOI | 8 | |
| Patient Account | 6 | |
| DOB | 4 | |

---

## Status: applied to the engine, config 0.3.2 (2026-08-19)

Everything below is now live in `concerns.json` / `patterns.library.json`.
Measured by `py -3.14 scripts/eval_samples.py`, which runs the real engine over
these 15 emails and scores it against columns D-L.

| | before (0.2.0) | after (0.3.2) |
|---|---|---|
| **Type of concern** | 11 / 15 | **15 / 15** |
| Claim ID | 8 hit, 6 wrong | **14 / 14** |
| DOS | 13 hit, 1 missed | **14 / 14** |
| Patient Account | 5 hit, 1 missed, 1 wrong | **6 / 6** |
| Prov TIN | 11 hit, 1 missed | **12 / 12** |
| Expected Amount | 12 hit, 2 wrong | **12 / 12** |
| DOI | 7 hit, 1 missed | **8 / 8** |
| DOB | 4 / 4 | **4 / 4** |
| Routed to review | 9 / 15 | 5 / 15 |

No field is wrong or missed on any sample. Measured with the embedding model
absent (rules + structure only), so these are the floor, not the ceiling.

### Required fields

On **Bill Status**: `claim_id`, `date_of_service`, `expected_amount`. On
**Claim Information**: nothing, because that concern *is* the sender asking to
be given the claim number - requiring it would flag every such email by
definition.

`expected_amount` also became `require_label: true` as a consequence. A real
email carries several figures (billed, paid, check amount); grabbing an
unanchored one would silently satisfy a required field with the wrong number
and stop the email routing for review. Prose aliases (`charge`, `charge was`,
`amount of`) keep "The charge was $1,250.00" working.

### The five rows that still route to review

All five are correct behaviour, not misses:

| # | Why |
|---|---|
| 2 | 42% confidence - weakly phrased appeal-receipt question, below the 55% accept bar |
| 5 | `expected_amount` missing - the `Amount:` line holds a **date** |
| 7 | `expected_amount` ambiguous - three different amounts in one email |
| 10 | `expected_amount` missing - the email quotes no figure at all |
| 12 | `expected_amount` ambiguous - five amounts, one per date of service |

Rows 7 and 12 are the multi-value gap in Finding 5. Once amounts pair with
their dates, both stop being ambiguous.

---

## Finding 1 - the reason layer has almost nothing to predict

This is the important one, and it confirms the `_OPEN_QUESTION` already written
into `concerns.json`.

The four reasons under Bill Status - *Completed processing*, *Completed
processing and denied*, *Not a bill on file*, *No claim on file; Missing
Information* - are **dispositions**. They are the outcome an agent records
**after** looking the bill up in the claims system.

Every one of these 15 emails is inbound provider mail **asking a question**. An
inbound email states the question, not the answer. So the correct reason is
blank on 14 of 15 rows, and the single exception ("Claim number request") is
the one reason in the taxonomy that describes a *request* rather than an
*outcome*.

**Recommendation.** Do not tune the reason rules against this set. Either:

- treat reason as an **output** the agent fills in after lookup, and drop it
  from the engine's prediction surface entirely; or
- re-cut the reason taxonomy into things an inbound email can actually say -
  "asking for EOB / check detail", "asking whether the bill was received",
  "appeal follow-up", "asking for payment date" - which is what these 15 emails
  divide into naturally.

Until that is decided, reason output should be labelled advisory in the UI.

### The trap row

Email #13 quotes its own prior call log inside a NOTES column:

> ...bill status ... **not on file**; bill and note faxed again today ...
> Amtrust **denied** ... as not documented in medical record

Both phrases are high-weight cues for `not_a_bill_on_file` and
`completed_processing_denied`. Neither is the disposition of *this* request -
they are history the sender is reporting back. Ground truth for E on that row
is **blank**.

Whatever reason rules survive must only read the newest message, and must not
fire on wording inside a quoted or tabulated history block.

---

## Finding 2 - concern is easy, and one phrase family carries it

Every Bill Status row matched on one of a small set of phrases:

```
bill status              status of the bill        status of bill
claim status             payment status            bill payment status
provide status           provide the status        claim status request
status update            check payment status      status of the attached appeal
unpaid bill              was received              date of receipt
when can we anticipate payment
```

These were missing from `bill_status.keyword_rules.positive` and have been
added:

- `claim status` / `claim status request` - several senders say "claim status"
  when they mean the bill's status. This currently risks pulling toward
  `claim_information`.
- `payment status` / `bill payment status`
- `status of the attached appeal` - appeal follow-up is a bill-status question

Claim Information fires on the sender asking to be **given** a number they do
not have:

```
claim number request     provide a claim number    provide the claim number
need the claim number    need a claim number       what is the claim number
requesting the claim
```

The distinction that matters: **"claim status" is Bill Status. "claim number
request" is Claim Information.** A bare "claim number" is not a signal either
way - it appears as a labelled field on nearly every row.

---

## Finding 3 - extraction must stay label-anchored

`DOS`, `DOI` and `DOB` share one date pattern. `Claim ID`, `Patient Account`
and `Prov TIN` share one digit-run shape. An unlabelled number cannot be
attributed to a field, so it is never claimed. Reporting nothing beats
reporting the wrong date - this matches what `extract.py` already does with
`require_label`.

Two rows prove it is the right call:

- **Email #4** has a date of birth sitting after a patient name with no label.
  Correctly refused.
- **Email #14** has the patient account in the subject line, unlabelled, in the
  same shape as the claim id that is also in the subject line. Correctly
  refused.

Neither is a bug. Do not "fix" them.

### Label aliases the samples require

All added to `concerns.json` in 0.3.0:

| Field | Add |
|---|---|
| Claim ID | `clm`, `your claim #`, `claim#` (no space) |
| DOS | `date service`, `dates of service` |
| Patient Account | `account ref#`, `acc.#`, `acct#` |
| Prov TIN | `taxid` (no space), `tax id#` |
| Expected Amount | `charged amount`, `billing amount`, `appeal amount`, `amount billed`, `bill amount`, `billed amt`, `tc` |
| DOI | `date injury` |
| DOB | `date birth` |

### Negative guards the samples require

Implemented as a new `reject_prefix` key on a field, plus `exclude_pattern_ref`
for the date/money overlap. Both are read by `extract.py`.

| Guard | Why |
|---|---|
| Claim ID must not follow `bill/`, `our bill`, `ref` | Email #1 carries `Ref #` and `Bill/Claim #` next to the real `Claim number`. The provider's own numbering is not the carrier claim id. |
| Prov TIN must not follow `provider`, `prov` | `Provider ID: <9 digits>` looks exactly like a TIN. |
| Expected Amount must not follow `paid`, `check` | A payment already issued is not what was billed. |
| A date match blocks a money match at the same position, and vice versa | Email #5 has a **date** typed into its `Amount:` line. Email #13 has `9/14/2026   $812.75` in one table cell. |
| A bare `claim` label only counts if it is the first one that yields a value | Otherwise "we submitted claim through electronically" scrapes the TIN off the following line. |

---

## Finding 4 - two pattern fixes for `patterns.library.json`

Checked against the live patterns, not assumed:

```
py -3.14 -c "import sys; sys.path.insert(0,'src'); from email_triage.config import load_config; p=load_config().patterns['us_date']; print(p.finditer('03.11.1994'))"
```

1. **`us_date` must accept dot separators.** Email #4 writes `03.11.1994` and
   `DOI: 03.11.1994`. The current pattern takes `/` and `-` only, and returns
   nothing for either. This is the one confirmed miss.

2. **A dotted date is currently read as an amount.** `currency_amount` matches
   `08.21` out of `03.11.1994`. The engine's `extract.py` has no mutual
   exclusion between the date and money patterns, so once fix 1 lands both will
   claim the same characters. Add the same date-blocks-money mask that
   `scripts/label_samples.py` uses.

Two things that are **already correct** and need no change:

- **Amounts without a comma.** `2288.60`, `7712.90`, `3377.40`, `4419.00`,
  `$527` all match. `currency_amount` carries a `\d+\.\d{2}` branch and a
  `(?<=\$)\d+` branch for exactly this.
- **Two-digit years.** `8/09/26`, `10/08/26`, `10/05/26` all match, and
  `_norm_date_iso` expands them.

---

## Finding 5 - the layout cases the current rule cannot reach

These are the backlog. Column D-L holds the correct answer anyway; column M
names the miss.

| Email | Field | Layout |
|---|---|---|
| #12 | DOS | five dates under **one** `dates of service` label, one per line, each paired with its own amount |
| #13 | DOS, Expected Amount | a **table**: `DOS` / `AMOUNT BILLED` / `NOTES` column headers with two data rows beneath |

Both are the same shape of problem: a label that heads a **column or list**
rather than pointing at a single adjacent value. A fixed character window
cannot see past the first entry.

Worth handling, because multi-DOS mail is common here - Email #7 has three
dates of service and three amounts, Email #12 has five of each. The pairing
matters too: the answer is not "five dates and five amounts" but five
*(date, amount)* pairs.

---

## Running it again

```
py -3.14 scripts/label_samples.py            # rewrite D-M in samples.xlsx
py -3.14 scripts/label_samples.py --check    # report only, write nothing
```

`samples.xlsx` holds real PHI. It is untracked but **not** covered by
`.gitignore` - one `git add -A` would put it in history permanently.
