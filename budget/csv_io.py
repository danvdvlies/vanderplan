"""CSV parsing for transaction import.

Canonical Vanderplan format (same columns the export writes):
    date, account, payee, category, amount, memo, cleared, is_income

`analyze_csv` is pure/read-only: it parses and classifies each row (ok /
duplicate / error, plus an unmatched-category flag) without writing anything,
so the view can show a preview before committing.
"""

import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation

from .models import Category, Transaction

_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y")
_TRUTHY = {"1", "true", "yes", "y", "t"}


def _parse_date(value: str):
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _truthy(value: str) -> bool:
    return value.strip().lower() in _TRUTHY


def analyze_csv(text: str, budget, account) -> list[dict]:
    """Parse CSV text into classified rows (no database writes).

    Each row dict carries the resolved values plus `status` ("ok"/"error"),
    `error`, `duplicate`, and `category_matched` (False when a category name was
    given but didn't match — that row still imports as Uncategorised).
    """
    categories = {
        c.name.lower(): c for c in Category.objects.filter(budget=budget)
    }
    rows = []
    reader = csv.DictReader(io.StringIO(text))
    for line_no, raw in enumerate(reader, start=2):  # line 1 is the header
        data = {
            (k or "").strip().lower(): (v or "").strip() for k, v in raw.items()
        }
        parsed_date = _parse_date(data.get("date", ""))
        try:
            amount = Decimal(data.get("amount", "").replace(",", ""))
        except InvalidOperation:
            amount = None

        payee = data.get("payee", "")
        memo = data.get("memo", "")
        is_income = _truthy(data.get("is_income", ""))
        cleared = _truthy(data.get("cleared", ""))
        category_name = data.get("category", "")

        category = None
        category_matched = True
        if category_name and not is_income:
            category = categories.get(category_name.lower())
            category_matched = category is not None

        error = None
        if parsed_date is None:
            error = "Invalid or missing date"
        elif amount is None:
            error = "Invalid or missing amount"

        duplicate = False
        if error is None:
            duplicate = Transaction.objects.filter(
                budget=budget, account=account, date=parsed_date,
                amount=amount, payee=payee,
            ).exists()

        rows.append(
            {
                "line": line_no,
                "date": parsed_date,
                "amount": amount,
                "payee": payee,
                "memo": memo,
                "category": category,
                "category_name": category_name,
                "category_matched": category_matched,
                "is_income": is_income,
                "cleared": cleared,
                "status": "error" if error else "ok",
                "error": error,
                "duplicate": duplicate,
            }
        )
    return rows
