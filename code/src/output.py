"""Formats the final output.csv row for one request."""
from __future__ import annotations


def fmt_amount(a):
    a = round(float(a), 2)
    if abs(a - round(a)) < 1e-9:
        return str(int(round(a)))
    return f"{a:.2f}"


def format_payment_plan(payments):
    if not payments:
        return "none"
    parts = [f"{d}:{fmt_amount(a)}" for d, a in payments]
    return "|".join(parts)


def format_spending_changes(changes):
    if not changes:
        return "none"
    return "|".join(changes[:3])


def build_explanation(request, decision, currency):
    status = decision["affordability_status"]
    method = decision["recommended_payment_method"]
    amount_safe = decision["amount_safe_to_pay"]
    min_balance = decision["min_balance"]
    requested = decision["requested_amount"]
    earliest = decision["earliest_date_for_full_payment"]
    changes = decision["spending_changes"]

    if status == "affordable_now":
        return (f"Pay {currency} {fmt_amount(requested)} today. The 90-day forecast keeps at "
                f"least {currency} {fmt_amount(min_balance)} available at all times.")
    if status == "affordable_with_plan" and method == "partial_payment":
        remaining = fmt_amount(requested - amount_safe)
        return (f"Pay {currency} {fmt_amount(amount_safe)} today and the remaining "
                f"{currency} {remaining} on {earliest}, once the forecast shows it is safe. "
                f"This keeps the balance at or above the {currency} {fmt_amount(min_balance)} minimum throughout.")
    if status == "affordable_with_plan" and method == "installments":
        n = len(decision["payments"])
        return (f"Use {n} installment payments starting {decision['payments'][0][0]}, matching a "
                f"supplied payment option. This stays above the {currency} {fmt_amount(min_balance)} "
                f"minimum balance for the full 90-day forecast.")
    if status == "affordable_with_plan" and method == "full_payment" and changes:
        return (f"Pay {currency} {fmt_amount(requested)} today after the listed spending changes free "
                f"up enough balance to stay above {currency} {fmt_amount(min_balance)}.")
    if status == "affordable_later":
        return (f"Paying the full {currency} {fmt_amount(requested)} today would break the "
                f"{currency} {fmt_amount(min_balance)} minimum balance requirement. The forecast shows "
                f"it becomes safe on {earliest}.")
    return (f"Paying {currency} {fmt_amount(requested)} is not expected to be safe within the 90-day "
            f"forecast without breaking the {currency} {fmt_amount(min_balance)} minimum balance "
            f"requirement, and no accepted payment method resolves it in time.")


def build_row(request, decision, currency):
    return {
        "request_id": request["request_id"],
        "amount_safe_to_pay": fmt_amount(decision["amount_safe_to_pay"]),
        "affordability_status": decision["affordability_status"],
        "recommended_payment_method": decision["recommended_payment_method"],
        "payment_plan": format_payment_plan(decision["payments"]),
        "earliest_date_for_full_payment": decision["earliest_date_for_full_payment"],
        "spending_changes_needed": format_spending_changes(decision["spending_changes"]),
        "decision_explanation": build_explanation(request, decision, currency),
    }
