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


def account_balances(account) -> dict:
    """Cleared / uncleared / working balances for an account.

    - working  = starting + all transactions (== account.current_balance)
    - cleared  = starting + cleared transactions (what the bank should show)
    - uncleared = working - cleared
    """
    cleared_txns = account.transactions.filter(cleared=True).aggregate(
        s=Sum("amount")
    )["s"] or ZERO
    cleared = account.starting_balance + cleared_txns
    working = account.current_balance
    return {"cleared": cleared, "uncleared": working - cleared, "working": working}


def reconcile_account(account, statement_balance: Decimal, on_date: date) -> dict:
    """Reconcile an account against a statement balance.

    If the cleared balance differs from the statement, an adjustment transaction
    (cleared + reconciled) is created for the difference. All currently-cleared,
    not-yet-reconciled transactions are then locked as reconciled. Returns a
    summary with the adjustment amount and the number of rows locked.
    """
    from django.utils import timezone

    cleared = account_balances(account)["cleared"]
    difference = (statement_balance - cleared).quantize(CENTS)

    adjustment = None
    if difference != ZERO:
        adjustment = Transaction.objects.create(
            user=account.user,
            account=account,
            date=on_date,
            payee="Reconciliation adjustment",
            amount=difference,
            cleared=True,
        )

    now = timezone.now()
    locked = account.transactions.filter(cleared=True, reconciled=False).update(
        reconciled=True, reconciled_at=now
    )
    if adjustment is not None:
        adjustment.refresh_from_db()  # the bulk update above also locked it
    return {"adjustment": adjustment, "difference": difference, "locked": locked}


def total_available_in_categories(user, month_start: date) -> Decimal:
    """Sum of available balances across all active, non-hidden categories."""
    total = ZERO
    categories = Category.objects.filter(user=user, is_active=True, is_hidden=False)
    for category in categories:
        total += category_available(user, category, month_start)
    return total


def to_be_assigned(user, month_start: date) -> Decimal:
    """Cash not yet assigned to any category (MVP definition from the spec).

    Also surfaced in the UI as "Ready to Assign".
    """
    return total_cash_available(user) - total_available_in_categories(user, month_start)


def income_for_month(user, month_start: date) -> Decimal:
    """Sum of transactions explicitly marked as income within the month."""
    start = month_floor(month_start)
    total = Transaction.objects.filter(
        user=user, is_income=True, date__gte=start, date__lt=next_month_start(start)
    ).aggregate(s=Sum("amount"))["s"]
    return total or ZERO


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


def category_history(user, category, num_months: int = 6) -> list[dict]:
    """Assigned / activity / available for a category over recent months."""
    base = month_floor(date.today())
    out = []
    for i in range(num_months - 1, -1, -1):
        m = add_months(base, -i)
        out.append(
            {
                "month": m,
                "assigned": category_assigned(user, category, m),
                "activity": category_activity(user, category, m),
                "available": category_available(user, category, m),
            }
        )
    return out


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


def move_between_categories(
    user, month_start: date, from_category, to_category, amount: Decimal
) -> None:
    """Move `amount` of assigned money from one category to another in a month.

    Implemented as a paired assignment change: the source month-assignment goes
    down by `amount` (it may go negative — the spec allows that specifically to
    move money out of a category) and the destination goes up by the same. Total
    assigned for the month is unchanged, so "To be assigned" is unaffected — only
    the two categories' available balances shift. Callers must have already
    confirmed ownership of both categories.
    """
    budget_month = get_or_create_budget_month(user, month_start)
    source, _ = BudgetAssignment.objects.get_or_create(
        user=user, budget_month=budget_month, category=from_category
    )
    source.assigned_amount = source.assigned_amount - amount
    source.save(update_fields=["assigned_amount", "updated_at"])

    destination, _ = BudgetAssignment.objects.get_or_create(
        user=user, budget_month=budget_month, category=to_category
    )
    destination.assigned_amount = destination.assigned_amount + amount
    destination.save(update_fields=["assigned_amount", "updated_at"])


# --------------------------------------------------------------------------
# Reports (read-only aggregates)
# --------------------------------------------------------------------------
def total_spending_for_month(user, month_start: date) -> Decimal:
    """Magnitude of all non-income expense (negative) transactions in the month."""
    start = month_floor(month_start)
    total = Transaction.objects.filter(
        user=user, is_income=False, amount__lt=0,
        date__gte=start, date__lt=next_month_start(start),
    ).aggregate(s=Sum("amount"))["s"] or ZERO
    return -total


def spending_by_category(user, month_start: date) -> dict:
    """Spending grouped by category for one month, largest first.

    Counts only non-income outflows (amount < 0). Transactions with no category
    are bucketed as "Uncategorised". Returns rows (each with percent of total)
    and the month's total spending.
    """
    start = month_floor(month_start)
    grouped = (
        Transaction.objects.filter(
            user=user, is_income=False, amount__lt=0,
            date__gte=start, date__lt=next_month_start(start),
        )
        .values("category", "category__name")
        .annotate(total=Sum("amount"))
    )
    rows = []
    total_spent = ZERO
    for entry in grouped:
        spent = -(entry["total"] or ZERO)
        if spent <= ZERO:
            continue
        rows.append({"name": entry["category__name"] or "Uncategorised", "spent": spent})
        total_spent += spent

    rows.sort(key=lambda r: r["spent"], reverse=True)
    for row in rows:
        row["percent"] = (
            (row["spent"] / total_spent * Decimal("100")).quantize(Decimal("1"))
            if total_spent
            else ZERO
        )
    return {"rows": rows, "total": total_spent}


def monthly_trend(user, num_months: int = 6) -> list[dict]:
    """Income, spending and net for the last `num_months` months (oldest first)."""
    base = month_floor(date.today())
    out = []
    for i in range(num_months - 1, -1, -1):
        m = add_months(base, -i)
        income = income_for_month(user, m)
        spending = total_spending_for_month(user, m)
        out.append(
            {"month": m, "income": income, "spending": spending, "net": income - spending}
        )
    return out


def net_worth_trend(user, num_months: int = 6) -> list[dict]:
    """End-of-month net worth for the last `num_months` months (oldest first).

    Net worth includes every account (credit-card balances count as the debt
    they are), computed as total starting balances plus all transactions dated
    on or before the end of each month — database-neutral, no SQLite date funcs.
    """
    starting_total = (
        Account.objects.filter(user=user).aggregate(s=Sum("starting_balance"))["s"]
        or ZERO
    )
    base = month_floor(date.today())
    out = []
    for i in range(num_months - 1, -1, -1):
        m = add_months(base, -i)
        txn_sum = Transaction.objects.filter(
            user=user, date__lt=next_month_start(m)
        ).aggregate(s=Sum("amount"))["s"] or ZERO
        out.append({"month": m, "net_worth": starting_total + txn_sum})
    return out


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
