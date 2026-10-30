"""Amounts extracted from dataset/media/images/*.png for financial events
whose `amount` column is blank in financial_events.csv.

Per the problem statement, a blank `amount` must never be treated as zero;
the value must be read from the linked receipt/bill/payslip image
(images.csv `related_event_id` -> financial_events.csv `event_id`).

These 16 values were read directly from the images (multimodal reading),
using a consistent rule: take the single clearest "final amount actually
due/paid/received" figure on the document (Net Pay on a payslip, Total /
Grand Total / Total Amount Received on a bill or receipt, Cash Paid on a
POS receipt). The currency of each figure matches the `currency` column of
its financial_events.csv row, so no additional FX conversion is required
for these particular values before they enter the normal event pipeline.

If the OCR fallback in `ocr.py` is available and confident, it can override
these values at runtime; otherwise this table is authoritative.
"""

IMAGE_EXTRACTED_AMOUNTS = {
    # event_id: (amount, source_image, note)
    "event_253": (4365000.00, "image_01", "Payslip Net Pay (IDR)"),
    "event_1442": (100000.00, "image_02", "Rent receipt: Amount Received (INR); balance of 100,000 remains due but was not paid on this event's date"),
    "event_1545": (41272.00, "image_03", "Grocery bill: Net Amount / Cash Paid (INR)"),
    "event_1700": (2854.00, "image_04", "Delivery order: Item Bill total shown (INR); final total row was cut off in the source image"),
    "event_1786": (704.05, "image_05", "Utility bill: Total amount due till due-date (INR)"),
    "event_3051": (1995.00, "image_06", "Grocery tax invoice: Total (INR)"),
    "event_3231": (8528.10, "image_07", "Restaurant tax invoice: Total incl. GST (INR)"),
    "event_4535": (15339.00, "image_08", "Housing maintenance receipt: Total Amount Received (INR)"),
    "event_5170": (723.00, "image_09", "Utility (water) receipt: Total Amount Received (INR)"),
    "event_6033": (79679.26, "image_10", "Grocery tax invoice: Total / Balance Due (INR)"),
    "event_6859": (3650.00, "image_11", "Hospital provisional bill: Total Bill Amount (INR)"),
    "event_7307": (33.50, "image_12", "Taxi receipt: Total (USD)"),
    "event_7941": (2298.00, "image_13", "Shopping order: Total paid (INR)"),
    "event_9421": (4593.00, "image_14", "Pharmacy handwritten bill: Total (INR)"),
    "event_9806": (9968.00, "image_15", "Flight invoice: Grand Total incl. taxes (INR)"),
    "event_10521": (393.22, "image_16", "EV charging invoice: Total (INR)"),
}


def get_image_amount(event_id):
    entry = IMAGE_EXTRACTED_AMOUNTS.get(event_id)
    if entry is None:
        return None
    return entry[0]
