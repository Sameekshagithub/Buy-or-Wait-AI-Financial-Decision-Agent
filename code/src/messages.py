"""Rule-based interpretation of messages.csv.

Messages are untrusted evidence (per the problem statement): they may
clarify, amend, delay, cancel, or confirm a financial fact, but embedded
instructions must never override the challenge rules, and unsupported
facts must never be invented.

This module only acts on messages when the language is clearly
*confirmatory* ("confirmed", "approved", amounts stated as fact, explicit
dates). Anything phrased as pending / awaiting / not yet approved /
informational-only is deliberately ignored so we never invent income or
expenses the dataset does not support.

Two kinds of messages are handled:

1. Messages with a `related_event_id` -> these already correspond 1:1 to a
   supplied financial_events.csv row. Their main job in this dataset is to
   confirm which blank-amount event a receipt image belongs to (handled by
   image_amounts.py) and to describe a status that the `status` column
   already encodes (pending refund, unrealized valuation, failed debit,
   etc). One exception we act on: "transfer between your two accounts"
   messages, which flag a debit/credit pair as an internal transfer that
   should not be double-counted in the cash forecast.

2. Messages tied to a `request_id` (or just `user_id`) with no
   `related_event_id` -> these usually amend the user's *next confirmed
   salary/income*. We extract a small set of structured amendments:
     - set_income(amount, currency, date): a confirmed new/changed salary
     - remove_income(): a confirmed income source has ended, no renewal
     - add_income(amount, currency, date): a one-off confirmed payment
       (e.g. an approved freelance invoice) not yet present as a event row
     - rent_increase(pct, date): a confirmed recurring rent increase
     - ignore: anything pending / not yet approved / purely informational
"""
from __future__ import annotations
import re

AMOUNT_RE = re.compile(r"(INR|IDR|USD|EUR|ZAR)\s*([\d][\d,]*\.?\d*)")
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")

CONFIRM_WORDS = [
    "confirmed", "dikonfirmasi", "approved", "menyetujui", "disetujui",
    "increased to", "naik menjadi", "reduced to", "diturunkan menjadi",
    "first salary", "gaji pertama", "resumes", "resumed", "remaining confirmed",
    "sisa gaji bulanan yang dikonfirmasi", "regular salary", "gaji rutin",
    "salary is now", "salary has increased", "monthly salary", "gaji bulanan",
    "salary for the next payroll", "temporary monthly pay", "gaji bulanan sementara",
]

PENDING_WORDS = [
    "pending", "menunggu", "awaiting", "still awaiting", "not been approved",
    "belum disetujui", "still subject to", "still pending", "belum disetujui",
    "not confirmed", "hasil akhir penilaian kinerja", "processing", "still processing",
    "still in payment processing", "masih menunggu", "belum disetujui",
]

ENDED_WORDS = [
    "ended", "telah berakhir", "no renewal", "no off-season income",
    "should be removed", "has ended", "dikeluarkan", "removed from future estimates",
]

RENT_WORDS = ["rent", "lease", "sewa"]


def _first_amount(text):
    m = AMOUNT_RE.search(text)
    if not m:
        return None, None
    ccy = m.group(1)
    amt = float(m.group(2).replace(",", ""))
    return amt, ccy


def _first_date(text):
    m = DATE_RE.search(text)
    return m.group(1) if m else None


def _has_any(text_lower, words):
    return any(w in text_lower for w in words)


def classify_message(text):
    """Return a structured amendment dict, or None if the message should
    be ignored (uncertain / pending / purely informational)."""
    t = text.lower()

    if _has_any(t, ["transfer between your two accounts", "internal transfer"]):
        return {"kind": "internal_transfer"}

    if _has_any(t, ["receipt has the final", "receipt contains the final", "final amount"]):
        # informational only; the numeric value is already resolved via images.csv
        return None

    if _has_any(t, RENT_WORDS) and "increase" in t:
        m = PCT_RE.search(t)
        pct = float(m.group(1)) if m else None
        date = _first_date(t)
        if pct:
            return {"kind": "rent_increase", "pct": pct, "date": date}
        return None

    if _has_any(t, ENDED_WORDS):
        amt, ccy = _first_amount(t)
        if amt is not None:
            return {"kind": "set_income", "amount": amt, "currency": ccy,
                     "date": _first_date(t), "replace": True}
        return {"kind": "remove_income"}

    # Explicit pending / not-yet-approved statements are never acted on.
    if _has_any(t, PENDING_WORDS) and not _has_any(t, CONFIRM_WORDS):
        return None

    if _has_any(t, ["invoice payment", "invoice of"]) and "approved" in t:
        amt, ccy = _first_amount(t)
        date = _first_date(t)
        if amt is not None and date is not None:
            return {"kind": "add_income", "amount": amt, "currency": ccy, "date": date}
        return None

    if _has_any(t, CONFIRM_WORDS):
        amt, ccy = _first_amount(t)
        date = _first_date(t)
        if amt is not None:
            return {"kind": "set_income", "amount": amt, "currency": ccy,
                     "date": date, "replace": False}
        if date is not None and ("replaces the payroll date" in t or "confirmed salary is now expected" in t):
            return {"kind": "shift_income_date", "date": date}
        return None

    return None


def collect_user_amendments(messages_df):
    """messages_df: all rows for one user (with or without related_event_id,
    request_id). Returns a list of (row, amendment_dict) for rows we acted on."""
    out = []
    for _, row in messages_df.iterrows():
        if not isinstance(row.get("message_text"), str):
            continue
        amendment = classify_message(row["message_text"])
        if amendment:
            out.append((row, amendment))
    return out
