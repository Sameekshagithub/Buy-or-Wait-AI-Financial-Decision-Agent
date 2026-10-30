"""Candidate payment-plan generation, deterministic safety validation, and
the fixed priority ranking described in the problem statement."""
from __future__ import annotations
from datetime import date, timedelta
import copy

from .forecast import Forecast

ALLOWED_STATUS = {"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"}
ALLOWED_METHOD = {"full_payment", "partial_payment", "installments", "wait", "not_recommended"}


def _parse(d):
    return date.fromisoformat(d) if isinstance(d, str) else d


class Candidate:
    def __init__(self, method, payments, changes, completion, payment_option_id=None):
        self.method = method
        self.payments = payments  # list[(date_str, amount)]
        self.changes = changes  # list[(kind, event_id, extra)]
        self.completion = completion  # date object
        self.payment_option_id = payment_option_id
        self.total_paid = sum(a for _, a in payments)
        self.first_date = _parse(payments[0][0]) if payments else None
        self.n_payments = len(payments)

    def rank_key(self):
        opt_num = 10 ** 9
        if self.payment_option_id:
            try:
                opt_num = int(self.payment_option_id.split("_")[-1])
            except Exception:
                opt_num = 10 ** 9
        return (
            1 if self.changes else 0,
            round(self.total_paid, 2),
            self.first_date,
            self.n_payments,
            opt_num,
        )


def _representative_event_id(category, history_by_cat, explicit_future_ids):
    if category in explicit_future_ids:
        return explicit_future_ids[category]
    hist = history_by_cat.get(category)
    if hist:
        return hist[-1]
    return f"category:{category}"


def _build_option_schedule(opt_row):
    payments = []
    n = int(opt_row["number_of_payments"])
    amt = float(opt_row["payment_amount"])
    first = _parse(str(opt_row["first_payment_date"])[:10])
    freq = opt_row.get("payment_frequency_days")
    freq = int(freq) if freq and freq == freq else 0
    d = first
    for i in range(n):
        payments.append((d.isoformat(), amt))
        d = d + timedelta(days=freq if freq else 0)
    return payments


def _apply_changes(cash_events, changes):
    """changes: list of (category, action, new_amount_or_none).
    Returns a new list of CashEvent with the change applied to every future
    occurrence of that category (stop -> zero; reduce -> capped magnitude)."""
    out = []
    change_map = {c[0]: c for c in changes}
    for e in cash_events:
        if e.category in change_map:
            _, action, new_amt = change_map[e.category]
            if e.amount < 0:  # only expenses are stoppable/reducible
                if action == "stop":
                    continue  # drop entirely
                elif action == "reduce":
                    e = copy.copy(e)
                    e.amount = -abs(new_amt)
        out.append(e)
    return out


def _pick_spending_changes(cash_events, request_date, desired_date, min_balance,
                            requested_amount, balance0, history_by_cat, explicit_future_ids,
                            payments_template):
    """Greedily pick up to 3 flexible categories (by total freed amount within
    the horizon) whose stop/reduce makes `payments_template` safe & on time.
    Returns (changes_for_output, modified_cash_events) or (None, None)."""
    eligible = {}
    for e in cash_events:
        if e.amount >= 0 or e.protected:
            continue
        if not (e.can_stop or e.can_reduce):
            continue
        if _parse(e.date) < request_date:
            continue
        eligible.setdefault(e.category, {"stop": e.can_stop, "reduce": e.can_reduce,
                                          "floor": e.floor or 0.0, "freed_stop": 0.0,
                                          "freed_reduce": 0.0})
        rec = eligible[e.category]
        rec["freed_stop"] += -e.amount
        if e.can_reduce:
            floor = e.floor if (e.floor is not None and e.floor == e.floor) else 0.0
            rec["freed_reduce"] += max(0.0, -e.amount - floor)

    ranked_categories = []
    for cat, rec in eligible.items():
        if rec["stop"]:
            ranked_categories.append((rec["freed_stop"], cat, "stop", 0.0))
        elif rec["reduce"]:
            ranked_categories.append((rec["freed_reduce"], cat, "reduce", rec["floor"]))
    ranked_categories.sort(key=lambda t: -t[0])

    for k in (1, 2, 3):
        top = ranked_categories[:k]
        if not top:
            break
        changes = [(cat, action, floor) for _, cat, action, floor in top]
        modified = _apply_changes(cash_events, changes)
        f = Forecast(balance0, modified, request_date.isoformat())
        safe, _ = f.simulate_payments(payments_template, min_balance)
        completion = _parse(payments_template[-1][0])
        if safe and completion <= desired_date:
            out_changes = []
            for _, cat, action, floor in top:
                ev_id = _representative_event_id(cat, history_by_cat, explicit_future_ids)
                if action == "stop":
                    out_changes.append(f"stop:{ev_id}")
                else:
                    out_changes.append(f"reduce_to:{ev_id}:{round(floor, 2)}")
            return out_changes, modified
    return None, None


def decide(request, profile, cash_events, options_df, history_by_cat, explicit_future_ids):
    request_date = _parse(request["request_date"])
    desired_date = _parse(request["desired_completion_date"])
    requested_amount = float(request["requested_amount"])
    allows_partial = str(request["allows_partial_payment"]).strip().lower() == "true"
    balance0 = float(profile["current_available_balance"])
    min_balance = float(profile["minimum_balance_to_keep"])
    accepted = set(str(profile["payment_methods_user_will_consider"]).split("|"))
    max_months = profile.get("max_installment_months")
    has_installment_pref = max_months is not None and max_months == max_months and str(max_months) != ""

    f0 = Forecast(balance0, cash_events, request["request_date"])
    amount_safe = round(f0.amount_safe_to_pay(requested_amount, min_balance), 2)
    earliest_date = f0.earliest_full_payment_date(requested_amount, min_balance)

    candidates = []

    # full payment today
    if "full_payment" in accepted:
        payments = [(request["request_date"], requested_amount)]
        safe, _ = f0.simulate_payments(payments, min_balance)
        if safe:
            candidates.append(Candidate("full_payment", payments, [], request_date))
        else:
            changes, modified = _pick_spending_changes(
                cash_events, request_date, desired_date, min_balance, requested_amount,
                balance0, history_by_cat, explicit_future_ids, payments)
            if changes:
                candidates.append(Candidate("full_payment", payments, changes, request_date))

    # wait: full payment on the earliest safe date (no changes)
    if "full_payment" in accepted and earliest_date and earliest_date != request["request_date"]:
        payments = [(earliest_date, requested_amount)]
        candidates.append(Candidate("wait", payments, [], _parse(earliest_date)))

    # partial payment
    if (allows_partial and "partial_payment" in accepted and 0 < amount_safe < requested_amount
            and earliest_date and _parse(earliest_date) <= desired_date):
        remaining = round(requested_amount - amount_safe, 2)
        payments = [(request["request_date"], amount_safe), (earliest_date, remaining)]
        safe, _ = f0.simulate_payments(payments, min_balance)
        if safe:
            candidates.append(Candidate("partial_payment", payments, [], _parse(earliest_date)))

    # installments
    if "installments" in accepted and has_installment_pref:
        for _, opt in options_df.iterrows():
            if opt["payment_method"] != "installments":
                continue
            schedule = _build_option_schedule(opt)
            months = (_parse(schedule[-1][0]) - request_date).days / 30.0
            if months > float(max_months) + 0.5:
                continue
            safe, _ = f0.simulate_payments(schedule, min_balance)
            if safe:
                candidates.append(Candidate("installments", schedule, [], _parse(schedule[-1][0]),
                                             payment_option_id=opt["payment_option_id"]))

    eligible = [c for c in candidates if c.completion <= desired_date]

    if eligible:
        best = min(eligible, key=lambda c: c.rank_key())
        if best.method == "full_payment" and best.completion == request_date and not best.changes:
            status = "affordable_now"
        elif best.method == "wait":
            status = "affordable_later"
        else:
            status = "affordable_with_plan"
        method = best.method
        payments = best.payments
        changes = best.changes
    else:
        wait_candidates = [c for c in candidates if c.method == "wait"]
        if wait_candidates:
            best = wait_candidates[0]
            status = "affordable_later"
            method = "wait"
            payments = best.payments
            changes = []
        elif "full_payment" in accepted and earliest_date:
            status = "affordable_later"
            method = "wait"
            payments = [(earliest_date, requested_amount)]
            changes = []
        else:
            status = "not_affordable"
            method = "not_recommended"
            payments = []
            changes = []

    return {
        "amount_safe_to_pay": amount_safe,
        "affordability_status": status,
        "recommended_payment_method": method,
        "payments": payments,
        "earliest_date_for_full_payment": earliest_date or "",
        "spending_changes": changes,
        "requested_amount": requested_amount,
        "min_balance": min_balance,
        "balance0": balance0,
    }
