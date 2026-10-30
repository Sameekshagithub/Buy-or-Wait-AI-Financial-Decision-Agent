"""90-day day-level balance forecasting and the deterministic safety check."""
from __future__ import annotations
from datetime import date, timedelta


def _parse(d):
    return date.fromisoformat(d)


class Forecast:
    """Precomputes the baseline cumulative balance for every day in
    [request_date, request_date + horizon_days], given a starting balance
    and a list of CashEvent objects (already filtered to cash-relevant).

    balance_at(day_index) = balance0 + sum of all cash_events with
    date <= day's date.
    """

    def __init__(self, balance0, cash_events, request_date_str, horizon_days=90):
        self.request_date = _parse(request_date_str)
        self.horizon_days = horizon_days
        self.dates = [self.request_date + timedelta(days=i) for i in range(horizon_days + 1)]
        daily_delta = [0.0] * (horizon_days + 1)
        for ev in cash_events:
            d = _parse(ev.date) if isinstance(ev.date, str) else ev.date
            idx = (d - self.request_date).days
            if 0 <= idx <= horizon_days:
                daily_delta[idx] += ev.amount
        bal = balance0
        balances = []
        for i in range(horizon_days + 1):
            bal += daily_delta[i]
            balances.append(bal)
        self.base_balance = balances  # base_balance[i] = balance at end of day i, before any request payment
        # suffix min from day i to end
        suf = [0.0] * (horizon_days + 1)
        suf[-1] = balances[-1]
        for i in range(horizon_days - 1, -1, -1):
            suf[i] = min(balances[i], suf[i + 1])
        self.suffix_min = suf

    def day_index(self, date_str):
        d = _parse(date_str)
        return (d - self.request_date).days

    def date_at(self, idx):
        return (self.request_date + timedelta(days=idx)).isoformat()

    def amount_safe_to_pay(self, requested_amount, min_balance):
        """Largest lump sum payable on day 0 (request_date) that keeps the
        balance >= min_balance for the whole horizon."""
        safe = self.suffix_min[0] - min_balance
        return max(0.0, min(safe, requested_amount))

    def earliest_full_payment_date(self, requested_amount, min_balance):
        """First day >= request_date at which paying the *full* requested
        amount as a single lump sum keeps the balance safe for the rest of
        the horizon (baseline must also already be safe on every day before
        that payment day)."""
        baseline_ok_so_far = True
        for i in range(self.horizon_days + 1):
            if i > 0 and self.base_balance[i - 1] < min_balance - 1e-6:
                baseline_ok_so_far = False
            if not baseline_ok_so_far:
                continue
            if self.suffix_min[i] - requested_amount >= min_balance - 1e-6:
                return self.date_at(i)
        return None

    def simulate_payments(self, payments, min_balance):
        """payments: list of (date_str, amount). Returns (is_safe, min_balance_reached)."""
        delta = [0.0] * (self.horizon_days + 1)
        for d, amt in payments:
            idx = self.day_index(d)
            if idx < 0:
                idx = 0
            if idx > self.horizon_days:
                continue
            delta[idx] += amt
        running_extra = 0.0
        min_bal = None
        for i in range(self.horizon_days + 1):
            running_extra += delta[i]
            bal = self.base_balance[i] - running_extra
            if min_bal is None or bal < min_bal:
                min_bal = bal
        return (min_bal is not None and min_bal >= min_balance - 1e-6), min_bal
