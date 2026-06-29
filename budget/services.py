"""
Pure budgeting calculations.

All money is Decimal. All date math is database-neutral (plain Python date
arithmetic and `__lte` / `__lt` filters) so the same code runs on SQLite and
PostgreSQL without SQLite-specific date functions.
"""

import calendar
from datetime import date
from decimal import ROUND_CEILING, Decimal

from django.db.models import Sum

from .models import (
    Account,
    BudgetAssignment,
    BudgetMonth,
    Category,
    Goal,
    Transaction,
)

ZERO = Decimal("0.00")
CENTS = Decimal("0.01")


# --------------------------------------------------------------------------
# Date helpers
# --------------------------------------------------------------------------
def month_floor(d: date) -> date:
    """First day of the month containing `d`."""
    return date(d.year, d.month, 1)


def add_months(d: date, n: int) -> date:
    """Add n months to `d`, clamping the day to the target month's length.

    e.g. add_months(2026-06-28, 3) -> 2026-09-28
         add_months(2026-01-31, 1) -> 2026-02-28
    """
    total = d.month - 1 + n
    year = d.year + total // 12
    month = total % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def next_month_start(month_start: date) -> date:
    """First day of the month after `month_start`."""
    return add_months(month_floor(month_start), 1)


def month_difference(from_month: date, to_month: date) -> int:
    """Whole-month difference between two month-starts (to - from)."""
    return (to_month.year - from_month.year) * 12 + (to_month.month - from_month.month)


def get_or_create_budget_month(user, month_start: date) -> BudgetMonth:
    """Fetch (or create) the BudgetMonth row, normalising to day 1."""
    bm, _ = BudgetMonth.objects.get_or_create(
        user=user, month_start=month_floor(month_start)
    )
    return bm


# --------------------------------------------------------------------------
# Category figures
# --------------------------------------------------------------------------
def category_assigned(user, category, month_start: date) -> Decimal:
    """Money assigned to this category in exactly this month."""
    total = BudgetAssignment.objects.filter(
        user=user, category=category, budget_month__month_start=month_floor(month_start)
    ).aggregate(s=Sum("assigned_amount"))["s"]
    return total or ZERO


def category_activity(user, category, month_start: date) -> Decimal:
    """Sum of transaction amounts for this category within this month.

    Expenses are negative, so this is typically negative.
    """
    start = month_floor(month_start)
    total = Transaction.objects.filter(
        user=user, category=category, date__gte=start, date__lt=next_month_start(start)
    ).aggregate(s=Sum("amount"))["s"]
    return total or ZERO


def category_available(user, category, month_start: date) -> Decimal:
    """Available balance for the category as of the end of `month_start`.

    The recursive spec definition
        available(m) = available(m-1) + assigned(m) + activity(m)
    telescopes to the sum of *all* assignments and activity up to and including
    this month. Computing it that way is a single pair of aggregate queries and
    needs no BudgetMonth row to exist for intermediate months.
    """
    start = month_floor(month_start)
    end = next_month_start(start)

    assigned = BudgetAssignment.objects.filter(
        user=user, category=category, budget_month__month_start__lte=start
    ).aggregate(s=Sum("assigned_amount"))["s"] or ZERO

    activity = Transaction.objects.filter(
        user=user, category=category, date__lt=end
    ).aggregate(s=Sum("amount"))["s"] or ZERO

    return assigned + activity


# --------------------------------------------------------------------------
# Cash / to-be-assigned
# --------------------------------------------------------------------------
def total_cash_available(user) -> Decimal:
    """Sum of active account balances.

    Assumption (documented for MVP): credit-card accounts are excluded because
    their balances are debt, not spendable cash. Special credit-card budgeting
    is out of scope for the MVP.
    """
    total = ZERO
    accounts = (
        Account.objects.filter(user=user, is_active=True)
        .exclude(account_type=Account.CREDIT_CARD)
    )
    for account in accounts:
        total += account.current_balance
    return total


def total_available_in_categories(user, month_start: date) -> Decimal:
    """Sum of available balances across all active, non-hidden categories."""
    total = ZERO
    categories = Category.objects.filter(user=user, is_active=True, is_hidden=False)
    for category in categories:
        total += category_available(user, category, month_start)
    return total


def to_be_assigned(user, month_start: date) -> Decimal:
    """Cash not yet assigned to any category (MVP definition from the spec)."""
    return total_cash_available(user) - total_available_in_categories(user, month_start)


# --------------------------------------------------------------------------
# Goals
# --------------------------------------------------------------------------
def funded_percent(available: Decimal, target: Decimal) -> Decimal:
    """Funded percentage, capped at 100. Zero target -> 0 (hidden)."""
    if target is None or target <= ZERO:
        return ZERO
    pct = (available / target) * Decimal("100")
    return min(Decimal("100"), pct).quantize(Decimal("1"))


def months_remaining(month_start: date, due_date: date) -> int:
    """Months available to fund a goal, from `month_start` to its due month.

    NOTE: the spec prose says "inclusive", but its own worked example treats a
    goal due three months out as $220 / 3 = $73.34 (section 3, and success
    criterion #11). We honour the worked example: this returns the whole-month
    distance to the due month, with a floor of 1 (a goal due this month or
    overdue must be funded in full this month).
    """
    diff = month_difference(month_floor(month_start), month_floor(due_date))
    return max(1, diff)


def needed_this_month(goal: Goal, available: Decimal, month_start: date) -> Decimal:
    """How much to assign this month to stay on track for the goal.

    - Due this month / overdue / no due date: the full remaining shortfall.
    - Due in the future: shortfall spread across the remaining months, rounded
      UP to the cent so that funding it each month actually reaches the target
      (220 / 3 = 73.333... -> 73.34).
    """
    shortfall = max(goal.target_amount - available, ZERO)
    if shortfall == ZERO:
        return ZERO
    if goal.due_date is None:
        return shortfall.quantize(CENTS)

    months = months_remaining(month_start, goal.due_date)
    if months <= 1:
        return shortfall.quantize(CENTS)
    return (shortfall / months).quantize(CENTS, rounding=ROUND_CEILING)


def active_goal_for(category) -> Goal | None:
    """The category's soonest-due active goal, if any."""
    return category.goals.filter(is_active=True).order_by("due_date").first()


def advance_goal(goal: Goal) -> Goal:
    """Move a repeating goal's due date forward by its repeat interval."""
    if goal.due_date and goal.repeat_interval_months:
        goal.due_date = add_months(goal.due_date, goal.repeat_interval_months)
        goal.save(update_fields=["due_date", "updated_at"])
    return goal


# --------------------------------------------------------------------------
# Composite rows for the budget screen / dashboard
# --------------------------------------------------------------------------
def goal_status(goal, available, target, month_start) -> str:
    """Human-readable status label for a category row."""
    if goal is None:
        return "No goal"
    if available < ZERO:
        return "Overspent"
    if target and target > ZERO:
        diff = month_difference(month_floor(month_start), month_floor(goal.due_date)) if goal.due_date else None
        if available >= target:
            return "Funded"
        if diff is not None and diff <= 0:
            return "Due now"
        return "Underfunded"
    return "On track"


def build_category_row(user, category, month_start: date) -> dict:
    """All figures the budget table needs for one category."""
    assigned = category_assigned(user, category, month_start)
    activity = category_activity(user, category, month_start)
    available = category_available(user, category, month_start)
    goal = active_goal_for(category)

    target = goal.target_amount if goal else ZERO
    needed = needed_this_month(goal, available, month_start) if goal else ZERO
    pct = funded_percent(available, target) if goal else ZERO

    return {
        "category": category,
        "assigned": assigned,
        "activity": activity,
        "available": available,
        "goal": goal,
        "target": target,
        "needed_this_month": needed,
        "funded_percent": pct,
        "funded_percent_bar": max(Decimal("0"), pct),
        "status": goal_status(goal, available, target, month_start),
    }


def fund_category(user, category, month_start: date) -> Decimal:
    """Assign whatever is still needed this month to reach the category's goal.

    `needed_this_month` is computed relative to the category's current available
    balance (which already includes this month's existing assignment), so we
    *add* it to the existing assignment rather than overwrite it. Returns the
    amount added (0 if there is no goal or nothing is needed).
    """
    row = build_category_row(user, category, month_start)
    needed = row["needed_this_month"]
    if needed <= ZERO:
        return ZERO

    budget_month = get_or_create_budget_month(user, month_start)
    assignment, _ = BudgetAssignment.objects.get_or_create(
        user=user, budget_month=budget_month, category=category
    )
    assignment.assigned_amount = assignment.assigned_amount + needed
    assignment.save(update_fields=["assigned_amount", "updated_at"])
    return needed


def build_budget_groups(user, month_start: date) -> list[dict]:
    """Grouped category rows for the budget screen, ordered by group/category."""
    groups = []
    qs = (
        Category.objects.filter(user=user, is_active=True, is_hidden=False)
        .select_related("category_group")
        .order_by("category_group__sort_order", "category_group__name", "sort_order", "name")
    )
    current_group = None
    bucket = None
    for category in qs:
        if current_group is None or category.category_group_id != current_group.id:
            current_group = category.category_group
            bucket = {"group": current_group, "rows": []}
            groups.append(bucket)
        bucket["rows"].append(build_category_row(user, category, month_start))
    return groups
