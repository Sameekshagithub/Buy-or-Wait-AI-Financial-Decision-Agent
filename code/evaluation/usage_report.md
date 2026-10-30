# Token Usage and Cost Report

## Summary

This solution is **fully deterministic / rule-based**. The final
full-dataset run that produced `output.csv` (250 requests from
`dataset/requests.csv`) made **zero calls to any LLM API**. All financial
reasoning (currency conversion, recurrence detection, 90-day balance
forecasting, candidate-plan generation, safety validation, ranking, and
explanation text) is implemented directly in Python (`code/src/`).

The only place a foundation model was used at all was **offline, once**,
by the developer (not at run time): reading the 16 receipt/payslip images
in `dataset/media/images/` to extract the blank `amount` values required
by the problem statement. Those 16 extracted numbers are hard-coded, with
their source image and the extraction rule documented, in
`code/src/image_amounts.py`. This is a one-time, non-repeating step; it is
not part of the per-request pipeline and is not re-invoked when
`code/main.py` is run.

| Metric | Value |
|---|---|
| Model provider(s) used at run time | none |
| Model name(s) used at run time | none |
| Model calls (full-dataset run) | 0 |
| Input tokens (full-dataset run) | 0 |
| Output tokens (full-dataset run) | 0 |
| Total tokens (full-dataset run) | 0 |
| Average tokens per request | 0 |
| Estimated total cost (full-dataset run) | $0.00 |
| Estimated cost per request | $0.00 |

## One-time, offline image-reading step (not part of the run-time pipeline)

| Metric | Value |
|---|---|
| Model provider | Anthropic |
| Model | Claude (multimodal chat, used interactively by the developer) |
| Images read | 16 |
| Purpose | Extract the single blank `amount` value for the 16 financial_events.csv rows whose amount is missing, per the linked image in images.csv |
| Repeated on every run? | No -- values are cached in code/src/image_amounts.py |

## Why zero cost at run time

The problem statement explicitly allows (and the AGENTS.md/README strongly
recommend) a hybrid architecture where an LLM interprets unstructured
evidence (messages/images) while a deterministic engine does the financial
math and safety checks. In this submission:

- **Messages** are interpreted with a documented rule-based/regex parser
  (`code/src/messages.py`) rather than an LLM call, so the pipeline is
  reproducible, auditable, and free to re-run.
- **Images** are a small, fixed set (16, all resolved once offline as
  described above), so a per-run OCR/vision API call was not necessary.

If a participant wants to swap in a live LLM call for message or image
interpretation (e.g. to generalize beyond the phrasings observed in this
dataset), `code/src/messages.py` and `code/src/image_amounts.py` are the
two integration points; the forecasting/ranking/validation layers in
`code/src/forecast.py` and `code/src/plans.py` do not need to change.
