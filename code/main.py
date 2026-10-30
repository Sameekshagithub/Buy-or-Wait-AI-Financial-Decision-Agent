#!/usr/bin/env python3
"""Buy or Wait? -- entry point.

Usage:
    python3 code/main.py [--dataset PATH] [--out PATH]

Reads dataset/requests.csv (and all supporting files) and writes one
prediction row per request to output.csv (repository root by default).

This solution is fully deterministic / rule-based (no LLM calls are made),
so evaluation/usage_report.md reports zero token usage and zero cost. See
README.md for the full pipeline description and design rationale.
"""
from __future__ import annotations
import argparse
import os
import sys
import time
import csv

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.loader import Dataset
from src.fx import FxConverter
from src.events import build_user_cash_events
from src.plans import decide
from src.output import build_row

OUTPUT_COLUMNS = [
    "request_id", "amount_safe_to_pay", "affordability_status",
    "recommended_payment_method", "payment_plan",
    "earliest_date_for_full_payment", "spending_changes_needed",
    "decision_explanation",
]


def run(dataset_dir, out_path):
    t0 = time.time()
    ds = Dataset(dataset_dir)
    fx = FxConverter(ds.exchange_rates)

    rows = []
    for _, request in ds.requests.iterrows():
        user_id = request["user_id"]
        profile, cash_events, history_by_cat, explicit_future_ids = build_user_cash_events(
            user_id, ds, fx, request["request_date"])
        options_df = ds.payment_options_for_request(request["request_id"])
        decision = decide(request, profile, cash_events, options_df, history_by_cat, explicit_future_ids)
        row = build_row(request, decision, profile["home_currency"])
        rows.append(row)

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    elapsed = time.time() - t0
    print(f"Wrote {len(rows)} predictions to {out_path} in {elapsed:.1f}s")
    return rows


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(here)
    parser = argparse.ArgumentParser(description="Buy or Wait? financial agent")
    parser.add_argument("--dataset", default=os.path.join(repo_root, "dataset"))
    parser.add_argument("--out", default=os.path.join(repo_root, "output.csv"))
    args = parser.parse_args()
    run(args.dataset, args.out)


if __name__ == "__main__":
    main()
