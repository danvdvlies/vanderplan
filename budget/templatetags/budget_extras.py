"""Custom template filters for the budgeting UI."""

from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def money(value):
    """Format a number as currency: 1234.5 -> "$1,234.50", -45.2 -> "-$45.20".

    The sign goes before the dollar sign (conventional) rather than after it.
    Returns "$0.00" for blank/None and leaves un-parseable values untouched.
    """
    if value is None or value == "":
        return "$0.00"
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    sign = "-" if amount < 0 else ""
    return f"{sign}${abs(amount):,.2f}"
