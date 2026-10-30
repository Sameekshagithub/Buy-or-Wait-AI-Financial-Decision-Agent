"""Currency conversion using fixed dated exchange rates.

Only exact (rate_date, from_currency, to_currency) rows are supplied in
exchange_rates.csv. We look up the exact triple first. If it is missing
(shouldn't happen for this dataset, verified during analysis) we fall back
to the closest earlier date for the same currency pair, and finally to an
inverted rate if only the reverse pair is available.
"""
from __future__ import annotations
import bisect
from collections import defaultdict


class FxConverter:
    def __init__(self, fx_df):
        # index: (from_ccy, to_ccy) -> sorted list of (date_str, rate)
        self._table = defaultdict(list)
        for _, row in fx_df.iterrows():
            key = (row["from_currency"], row["to_currency"])
            self._table[key].append((row["rate_date"], float(row["rate"])))
        for key in self._table:
            self._table[key].sort(key=lambda t: t[0])

    def _lookup_pair(self, date_str, frm, to):
        rows = self._table.get((frm, to))
        if not rows:
            return None
        dates = [r[0] for r in rows]
        # exact match
        idx = bisect.bisect_left(dates, date_str)
        if idx < len(dates) and dates[idx] == date_str:
            return rows[idx][1]
        # fall back to most recent date <= date_str
        if idx > 0:
            return rows[idx - 1][1]
        # otherwise use earliest available
        if rows:
            return rows[0][1]
        return None

    def rate(self, date_str, frm, to):
        if frm == to:
            return 1.0
        r = self._lookup_pair(date_str, frm, to)
        if r is not None:
            return r
        r = self._lookup_pair(date_str, to, frm)
        if r is not None and r != 0:
            return 1.0 / r
        raise ValueError(f"No FX rate for {frm}->{to} on {date_str}")

    def convert(self, amount, date_str, frm, to):
        return amount * self.rate(date_str, frm, to)
