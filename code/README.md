# Buy or Wait? — Solution

A fully deterministic, rule-based financial-forecasting agent (no LLM calls)
that answers "can I afford this?" for every row in `dataset/requests.csv`.

## Run it

```bash
python3 code/main.py
```

No dependencies beyond `pandas` (see `requirements.txt`). By default it
reads `dataset/` and writes `output.csv` to the repository root:

```bash
python3 code/main.py --dataset dataset --out output.csv
```

## Pipeline

```
requests.csv row
      │
      ▼
financial_profiles.csv + financial_events.csv   (per user_id)
      │  currency conversion (fx.py, dated exact-match rates)
      │  blank-amount events resolved from receipt/payslip images
      │  (image_amounts.py — 16 events, manually read from the PNGs)
      │  message amendments applied (messages.py — confirmed salary
      │  changes/endings/rent increases only; pending/awaiting facts
      │  are never acted on, so we never invent unsupported income)
      ▼
events.py: cash-relevant event stream
      │  recurrence is detected statistically per (user, category) from
      │  that user's own history (median interval + coefficient of
      │  variation on the dated history) rather than a fixed category
      │  whitelist, since which categories are recurring is personal
      │  (one user's family_support or healthcare payment is monthly,
      │  another's is a one-off). Variable-but-essential spending
      │  (groceries, transport, dining) is projected at its historical
      │  average rather than the latest value. Recurring DEBITS
      │  (expenses/subscriptions/loan instalments) are projected forward
      │  as the conservative assumption that known commitments continue.
      │  Future INCOME is only ever taken from an explicit
      │  scheduled/pending row already in financial_events.csv (the "next
      │  confirmed salary") or a message that clearly confirms a new
      │  figure -- except for salary specifically, which is additionally
      │  assumed to repeat every ~30 days once at least one confirmed
      │  occurrence (historical or message-confirmed) is on record, since
      │  a monthly paycheque is the one form of recurring income the
      │  problem's own sample answers rely on being forecast forward.
      ▼
forecast.py: day-by-day 90-day balance simulation
      │  amount_safe_to_pay = suffix-min(day 0) - minimum_balance, capped
      │  earliest_date_for_full_payment = first day the full amount
      │  still clears every later day's suffix-min
      ▼
plans.py: candidate generation (full_payment / wait / partial_payment /
          each supplied installment option), spending-change search
          (up to 3 flexible categories, greedily, only when needed),
          deterministic day-by-day safety re-check, and the fixed
          6-rule priority ranking from the problem statement
      ▼
output.py: formats payment_plan / spending_changes_needed strings and
           a short, numbers-grounded decision_explanation
      ▼
output.csv
```

## Key design decisions

- **Deterministic core.** All money math (currency conversion, balance
  simulation, plan safety, ranking) is plain Python/pandas — no LLM in the
  loop, so results are reproducible and auditable. This also means
  `evaluation/usage_report.md` reports zero token usage / zero cost.
- **Images.** All 16 blank-`amount` events have exactly one linked image.
  Each was read directly (multimodal reading) using one consistent rule —
  take the clearest single "final amount" figure on the document (Net Pay
  on a payslip, Total/Grand Total/Total Amount Received on a bill or
  receipt). Values and the rule used are documented in
  `code/src/image_amounts.py`.
- **Messages.** Messages are treated as untrusted evidence. The parser
  (`code/src/messages.py`) only acts on clearly confirmatory language
  ("confirmed", "approved", a concrete amount + date). Anything phrased as
  pending, awaiting approval, or purely informational is ignored, so the
  system never invents income or expenses the dataset doesn't support.
  It also recognises "ended / no renewal" (drops the next salary),
  "transfer between your two accounts" (treated as a net-zero internal
  move and excluded from the cash forecast), and confirmed recurring
  rent increases.
- **Recurrence.** Recurrence is inferred per (user, category) from that
  user's own history: at least two historical rows, a median gap between
  5 and 100 days, and a coefficient of variation ≤ 0.5. This is
  deliberately general rather than a fixed category list, because which
  categories recur is personal (e.g. one user's `family_support` or
  `healthcare` payment is a monthly obligation, another's is a genuine
  one-off) — a hard-coded whitelist fit to the 26 visible samples would
  under- or over-count spending for the other 224 users in ways we can't
  see. Variable-but-essential spending (groceries/transport/dining) is
  projected at its historical *average* rather than the latest value, as a
  more representative conservative estimate. Salary is the one category
  given a fallback recurring assumption even from a single data point
  (see the pipeline diagram above), since forecasting future income at all
  requires assuming the next paycheque repeats; every other category needs
  the full statistical signal before being projected forward.
- **Spending changes.** Only events whose `flexibility` allows it *and*
  whose category is in the user's own `expense_categories_user_is_
  willing_to_reduce` / `..._to_stop` list are ever touched; protected
  categories are never modified. The engine tries the smallest number of
  changes (1, then 2, then 3) needed to make a plan safe, so "no spending
  changes" is preferred whenever possible per the ranking rules.
- **Ranking.** Candidates are filtered to those that are safe for the full
  90-day forecast *and* complete by `desired_completion_date`, then sorted
  by the exact 6-rule tuple from the problem statement (deadline already
  satisfied by the filter → no spending changes → lowest total paid →
  earliest first payment → fewest payments → lowest `payment_option_id`).

## Validation

`amount_safe_to_pay` bounds, installment-schedule exact-match to a
supplied `payment_option_id`, `payment_plan` chronological ordering, and
`spending_changes_needed` formatting are all checked in
`evaluation/main.py`, which also reports accuracy against
`dataset/sample_requests.csv` (used only for self-checking, never as
ground truth for `dataset/requests.csv`).

```bash
python3 code/evaluation/main.py
```

## Self-check against the 26 solved samples

Running `python3 code/evaluation/main.py` against `dataset/sample_requests.csv`
(never used as ground truth for the graded `dataset/requests.csv`) currently
scores:

- `affordability_status` match: ~72%
- `recommended_payment_method` match: ~80%
- `amount_safe_to_pay` within 1 unit: ~16% (categorical decisions are much
  closer than exact amounts — see limitations below)

One instructive miss is `request_05`: our forecast treats the user's
regular monthly salary as continuing (per the recurrence rule above) and
finds the request comfortably affordable, while the reference answer is
`not_affordable` with almost no safe amount. We could not find a rule in
the problem statement that both (a) explains this specific answer and
(b) does not badly regress several *other* samples when applied generally
(we tried disabling all income projection beyond the single explicit
"next confirmed salary" row and it dropped overall sample accuracy from
~72% to ~28%, since most other samples *do* rely on multiple future
paycheques being forecast). We left the general rule in place and
documented the disagreement rather than special-casing one sample.

## Known limitations / where this could improve with more time

- `amount_safe_to_pay` and other exact figures depend on assumptions
  (e.g. how many months of essential spending to project, which category
  gets which floor value) that won't always match the hidden methodology
  bit-for-bit, even when the categorical decision is right.
- Message interpretation is regex/keyword-based rather than an LLM call,
  by design (keeps the pipeline deterministic and free to run), but a
  model-based extractor (Claude/GPT via an API key in an environment
  variable) could be swapped in for `code/src/messages.py` to generalize
  beyond the observed phrasings, with the deterministic forecasting/
  safety-check layers left untouched.
