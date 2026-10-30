#!/usr/bin/env python3
"""Self-check harness.

1. Runs the pipeline against dataset/sample_requests.csv (which has
   solved output columns) and reports accuracy -- for the participant's
   own confidence only, never used as ground truth for the graded
   dataset/requests.csv.
2. Runs a set of structural/format validations against the final
   output.csv produced from dataset/requests.csv.
"""
from __future__ import annotations
import os
import sys
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CODE_DIR = os.path.dirname(HERE)
REPO_ROOT = os.path.dirname(CODE_DIR)
sys.path.insert(0, CODE_DIR)

from src.loader import Dataset
from src.fx import FxConverter
from src.events import build_user_cash_events
from src.plans import decide
from src.output import build_row


def score_samples(dataset_dir):
    ds = Dataset(dataset_dir)
    fx = FxConverter(ds.exchange_rates)
    samples = ds.sample_requests

    n = len(samples)
    correct_status = correct_method = correct_amount = 0
    for _, request in samples.iterrows():
        profile, cash_events, hist, exp = build_user_cash_events(
            request["user_id"], ds, fx, request["request_date"])
        options_df = ds.payment_options_for_request(request["request_id"])
        decision = decide(request, profile, cash_events, options_df, hist, exp)
        row = build_row(request, decision, profile["home_currency"])

        correct_status += row["affordability_status"] == request["affordability_status"]
        correct_method += row["recommended_payment_method"] == request["recommended_payment_method"]
        correct_amount += abs(float(row["amount_safe_to_pay"]) - float(request["amount_safe_to_pay"])) < 1.0

    print(f"[sample self-check] n={n}")
    print(f"  affordability_status accuracy : {correct_status/n:.2%}")
    print(f"  recommended_method accuracy   : {correct_method/n:.2%}")
    print(f"  amount_safe_to_pay exact-ish  : {correct_amount/n:.2%}")


def validate_output(dataset_dir, output_path):
    req = pd.read_csv(os.path.join(dataset_dir, "requests.csv"))
    out = pd.read_csv(output_path)
    opts = pd.read_csv(os.path.join(dataset_dir, "request_payment_options.csv"))

    ok = True
    expected_cols = ["request_id", "amount_safe_to_pay", "affordability_status",
                      "recommended_payment_method", "payment_plan",
                      "earliest_date_for_full_payment", "spending_changes_needed",
                      "decision_explanation"]
    if list(out.columns) != expected_cols:
        print("FAIL: columns mismatch", list(out.columns))
        ok = False

    if len(out) != len(req):
        print(f"FAIL: row count {len(out)} != {len(req)}")
        ok = False

    merged = out.merge(req[["request_id", "requested_amount"]], on="request_id", how="left")
    bad_bounds = merged[(merged.amount_safe_to_pay < -0.01) |
                         (merged.amount_safe_to_pay > merged.requested_amount + 0.01)]
    if len(bad_bounds):
        print(f"FAIL: {len(bad_bounds)} rows violate 0 <= amount_safe_to_pay <= requested_amount")
        ok = False

    allowed_status = {"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"}
    if not set(out.affordability_status).issubset(allowed_status):
        print("FAIL: unexpected affordability_status values", set(out.affordability_status) - allowed_status)
        ok = False

    allowed_method = {"full_payment", "partial_payment", "installments", "wait", "not_recommended"}
    if not set(out.recommended_payment_method).issubset(allowed_method):
        print("FAIL: unexpected recommended_payment_method values")
        ok = False

    def chron_ok(pp):
        if pp == "none":
            return True
        dates = [p.split(":")[0] for p in str(pp).split("|")]
        return dates == sorted(dates)

    if not out.payment_plan.apply(chron_ok).all():
        print("FAIL: payment_plan not chronological in some rows")
        ok = False

    inst = out[out.recommended_payment_method == "installments"]
    for _, row in inst.iterrows():
        cand = opts[(opts.request_id == row.request_id) & (opts.payment_method == "installments")]
        parts = row.payment_plan.split("|")
        n, amt = len(parts), float(parts[0].split(":")[1])
        if not any(o.number_of_payments == n and abs(o.payment_amount - amt) < 0.02
                   for _, o in cand.iterrows()):
            print(f"FAIL: {row.request_id} installment plan does not match a supplied option")
            ok = False

    print("VALIDATION " + ("PASSED" if ok else "FAILED"))
    return ok


if __name__ == "__main__":
    dataset_dir = os.path.join(REPO_ROOT, "dataset")
    output_path = os.path.join(REPO_ROOT, "output.csv")
    score_samples(dataset_dir)
    if os.path.exists(output_path):
        validate_output(dataset_dir, output_path)
    else:
        print(f"(skipping output validation -- {output_path} not found; run code/main.py first)")
