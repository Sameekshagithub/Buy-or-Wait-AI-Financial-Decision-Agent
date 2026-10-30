"""Reconstructs a user's cash-relevant event stream: historical actuals,
already-scheduled/pending future rows, and projected recurring expenses /
income, with message-based amendments applied.
"""
from __future__ import annotations
from datetime import date, timedelta
import statistics as stats

from .image_amounts import get_image_amount
from .messages import collect_user_amendments

CASH_DEBIT_TYPES = {"expense", "debt_payment", "investment_purchase"}
CASH_CREDIT_TYPES = {"income", "refund", "investment_sale"}
NON_CASH_TYPES = {"investment_valuation"}

# Categories that are near-universally billed on a fixed monthly cadence.
# When history only shows a single occurrence (e.g. the user's on-file
# history starts shortly before the request date), we still treat these as
# recurring monthly rather than one-off, since a single salary/rent/
# subscription/loan-instalment data point is itself strong evidence of a
# recurring commitment even without a second historical data point to
# measure the interval from.
DEFAULT_MONTHLY_CATEGORIES = {
    "salary", "rent", "debt_repayment", "utilities", "insurance",
    "music_subscription", "delivery_membership", "cloud_storage",
    "streaming", "gym", "housing",
}
DEFAULT_INTERVAL_DAYS = 30


def _parse(d):
    return date.fromisoformat(d)


def _fmt(d):
    return d.isoformat()


class CashEvent:
    __slots__ = ("event_id", "date", "amount", "category", "flexibility",
                 "floor", "source", "protected", "can_stop", "can_reduce")

    def __init__(self, event_id, dt, amount, category, flexibility, floor,
                 source, can_stop=False, can_reduce=False, protected=True):
        self.event_id = event_id
        self.date = dt  # ISO string
        self.amount = amount  # signed: credit positive, debit negative (home ccy)
        self.category = category
        self.flexibility = flexibility
        self.floor = floor
        self.source = source
        self.can_stop = can_stop
        self.can_reduce = can_reduce
        self.protected = protected


def _eligibility(category, flexibility, profile):
    protect = set(str(profile.get("expense_categories_to_protect") or "").split("|"))
    willing_reduce = set(str(profile.get("expense_categories_user_is_willing_to_reduce") or "").split("|"))
    willing_stop = set(str(profile.get("expense_categories_user_is_willing_to_stop") or "").split("|"))
    if category in protect:
        return False, False, True
    can_reduce = flexibility in ("reducible", "reducible_or_stoppable") and category in willing_reduce
    can_stop = flexibility in ("stoppable", "reducible_or_stoppable") and category in willing_stop
    return can_stop, can_reduce, False


def build_user_cash_events(user_id, ds, fx, request_date_str, horizon_days=90):
    """Returns (profile, list[CashEvent]) sorted by date, for the window
    [request_date_str, request_date_str + horizon_days]."""
    profile = ds.profile(user_id)
    home_ccy = profile["home_currency"]
    request_date = _parse(request_date_str)
    horizon_end = request_date + timedelta(days=horizon_days)

    raw = ds.events_for_user(user_id).to_dict("records")

    rows = []
    for r in raw:
        amount = r.get("amount")
        if amount is None or (isinstance(amount, float) and amount != amount):
            amount = get_image_amount(r["event_id"])
            if amount is None:
                continue  # no evidence available; cannot invent the value
        else:
            amount = float(amount)

        eff_date = r.get("settlement_date") or r.get("event_date")
        try:
            eff_date = _parse(str(eff_date)[:10])
        except Exception:
            continue

        ccy = r["currency"]
        try:
            home_amount = fx.convert(amount, _fmt(eff_date), ccy, home_ccy)
        except Exception:
            home_amount = amount  # last resort, should not trigger given fx coverage

        rows.append({
            "event_id": r["event_id"], "event_type": r["event_type"],
            "category": r["category"], "direction": r["direction"],
            "amount": home_amount, "date": eff_date, "status": r["status"],
            "flexibility": r.get("flexibility"),
            "floor": r.get("minimum_allowed_amount"),
            "linked": r.get("linked_event_id"),
        })

    # ---- message-based amendments (income only; see messages.py) ----
    msgs = ds.messages_for_user(user_id)
    amendments = collect_user_amendments(msgs)

    income_rows = [r for r in rows if r["category"] == "salary" and r["direction"] == "credit"]
    scheduled_income = [r for r in income_rows if r["status"] == "scheduled"]
    rent_multiplier = {}
    extra_synthetic = []
    removed_scheduled_income = False

    for _row, am in amendments:
        kind = am["kind"]
        if kind == "internal_transfer":
            ev_id = _row.get("related_event_id")
            if isinstance(ev_id, str):
                for r in rows:
                    if r["event_id"] == ev_id:
                        r["status"] = "cancelled"  # exclude from cash flow (netted internal move)
                        # also null out a same-day / same-amount opposite-direction match
                        for r2 in rows:
                            if (r2 is not r and r2["date"] == r["date"]
                                    and abs(abs(r2["amount"]) - abs(r["amount"])) < 0.01
                                    and r2["direction"] != r["direction"]):
                                r2["status"] = "cancelled"
                                break
        elif kind == "rent_increase":
            eff = am.get("date")
            rent_multiplier["rent"] = (1 + am["pct"] / 100.0,
                                        _parse(eff) if eff else request_date)
        elif kind == "remove_income":
            for r in scheduled_income:
                r["status"] = "cancelled"
            removed_scheduled_income = True
        elif kind == "set_income":
            amt, ccy, d = am.get("amount"), am.get("currency"), am.get("date")
            if amt is None:
                continue
            target_date = _parse(d) if d else request_date
            try:
                home_amt = fx.convert(amt, _fmt(target_date), ccy or home_ccy, home_ccy)
            except Exception:
                home_amt = amt
            if scheduled_income:
                r = scheduled_income[0]
                r["amount"] = home_amt
                if d:
                    r["date"] = target_date
                r["status"] = "scheduled"
            else:
                extra_synthetic.append({
                    "event_id": f"msg_income:{user_id}:{target_date}",
                    "event_type": "income", "category": "salary", "direction": "credit",
                    "amount": home_amt, "date": target_date, "status": "scheduled",
                    "flexibility": "fixed", "floor": None, "linked": None,
                })
        elif kind == "add_income":
            amt, ccy, d = am.get("amount"), am.get("currency"), am.get("date")
            if amt is None or d is None:
                continue
            target_date = _parse(d)
            try:
                home_amt = fx.convert(amt, _fmt(target_date), ccy or home_ccy, home_ccy)
            except Exception:
                home_amt = amt
            extra_synthetic.append({
                "event_id": f"msg_addincome:{user_id}:{target_date}",
                "event_type": "income", "category": "other_income", "direction": "credit",
                "amount": home_amt, "date": target_date, "status": "scheduled",
                "flexibility": "fixed", "floor": None, "linked": None,
            })
        elif kind == "shift_income_date":
            d = am.get("date")
            if d and scheduled_income:
                scheduled_income[0]["date"] = _parse(d)

    rows.extend(extra_synthetic)

    # ---- cash-relevance filter ----
    def is_cash_relevant(r):
        if r["status"] in ("cancelled", "failed"):
            return False
        if r["direction"] == "non_cash" or r["status"] == "unrealized":
            return False
        if r["direction"] == "credit" and r["status"] == "pending":
            return False  # reserve only settled/scheduled credits
        return True

    for r in rows:
        r["cash_relevant"] = is_cash_relevant(r)

    # ---- recurrence detection from historical settled rows ----
    history = [r for r in rows if r["status"] == "settled" and r["date"] <= request_date
               and r["cash_relevant"]]
    by_cat = {}
    for r in history:
        by_cat.setdefault(r["category"], []).append(r)

    events_out = []

    # explicit future rows already present (scheduled / pending, in window)
    explicit_future = [r for r in rows if r["cash_relevant"] and r["status"] in ("scheduled", "pending")
                        and request_date <= r["date"] <= horizon_end]
    explicit_anchor_dates = {}  # category -> latest anchor date used
    for r in explicit_future:
        can_stop, can_reduce, protected = _eligibility(r["category"], r.get("flexibility"), profile)
        signed = r["amount"] if r["direction"] == "credit" else -r["amount"]
        events_out.append(CashEvent(r["event_id"], _fmt(r["date"]), signed, r["category"],
                                     r.get("flexibility"), r.get("floor"), "explicit_future",
                                     can_stop, can_reduce, protected))
        prev = explicit_anchor_dates.get(r["category"])
        if prev is None or r["date"] > prev:
            explicit_anchor_dates[r["category"]] = r["date"]

    # Categories whose amount genuinely varies payment to payment (groceries,
    # transport, dining) are forecast using the historical average rather
    # than just the most recent value, which is more conservative and more
    # representative than any single latest data point. Every other
    # category uses its most recent observed amount. Recurrence itself is
    # detected purely statistically below (median interval + coefficient of
    # variation on the dated history) for EVERY category present in a
    # user's history -- "detect recurrence only when history supports it"
    # is a personalised, per-user, per-category question (e.g. one user may
    # have a recurring family_support or healthcare payment while another
    # does not), so no category is hard-excluded up front.
    VARIABLE_ESSENTIAL = {"groceries", "transport", "dining"}
    # Categories that are one-off/irregular by nature even when a user
    # happens to have 2+ historical rows close together by chance (e.g. two
    # unrelated shopping purchases, or a purchase + its refund). We still
    # allow them to be detected as recurring if the statistics genuinely
    # support it (some users do have a recurring shopping subscription-like
    # pattern), but we do not apply the single-point monthly fallback to
    # them the way we do for salary.
    NEVER_DEFAULT_MONTHLY = {"shopping", "entertainment", "work_expense", "investment", "windfall"}

    for category, group in by_cat.items():
        group_sorted = sorted(group, key=lambda r: r["date"])
        dates = [r["date"] for r in group_sorted]
        is_income = group_sorted[0]["direction"] == "credit"

        if len(dates) >= 2:
            diffs = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
            diffs = [d for d in diffs if d > 0]
            if not diffs:
                continue
            interval = int(round(stats.median(diffs)))
            mean_d = sum(diffs) / len(diffs)
            cv = (stats.pstdev(diffs) / mean_d) if mean_d else 999
            if interval < 5 or interval > 100 or cv > 0.5:
                if not (is_income and category == "salary"):
                    continue
                interval = 30  # salary: history exists but irregular -> assume monthly anyway
        elif is_income and category == "salary":
            # Only one historical salary payment on record. Salaries are
            # near-universally monthly, so default to a 30-day cadence
            # rather than treating a single data point as non-recurring.
            interval = 30
        else:
            continue

        last = group_sorted[-1]
        direction = last["direction"]
        flexibility = last.get("flexibility")
        floor = last.get("floor")
        can_stop, can_reduce, protected = _eligibility(category, flexibility, profile)

        if category in VARIABLE_ESSENTIAL:
            # Conservative forecast for variable-but-essential spending:
            # use the historical average amount, not just the latest one.
            last_amount = sum(r["amount"] for r in group_sorted) / len(group_sorted)
        else:
            last_amount = last["amount"]

        anchor_date = explicit_anchor_dates.get(category)
        start_from = anchor_date if anchor_date else last["date"]
        mult, mult_from = rent_multiplier.get(category, (1.0, None))

        next_date = start_from + timedelta(days=interval)
        n_generated = 0
        while next_date <= horizon_end and n_generated < 400:
            if next_date >= request_date:
                amt = last_amount
                if mult_from and next_date >= mult_from:
                    amt = amt * mult
                signed = amt if direction == "credit" else -amt
                events_out.append(CashEvent(
                    f"projected:{category}:{_fmt(next_date)}", _fmt(next_date), signed,
                    category, flexibility, floor, "projected", can_stop, can_reduce, protected))
                n_generated += 1
            next_date = next_date + timedelta(days=interval)

    events_out.sort(key=lambda e: e.date)

    history_by_cat = {}
    for cat, group in by_cat.items():
        history_by_cat[cat] = [r["event_id"] for r in sorted(group, key=lambda r: r["date"])]

    explicit_future_ids = {}
    for r in explicit_future:
        prev = explicit_future_ids.get(r["category"])
        if prev is None:
            explicit_future_ids[r["category"]] = r["event_id"]

    return profile, events_out, history_by_cat, explicit_future_ids
