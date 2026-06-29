"""
Views for the budgeting app.

Every view is login-required. Every object lookup is scoped with
`user=request.user` (via `_owned`) so an ID from the URL can never reach
another user's data.
"""

import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction as db_transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from . import csv_io, services, starter
from .forms import (
    AccountForm,
    CategoryForm,
    CategoryGroupForm,
    CsvImportForm,
    GoalForm,
    IncomeForm,
    RegisterForm,
    TransactionForm,
)
from .models import (
    Account,
    BudgetAssignment,
    Category,
    CategoryGroup,
    Goal,
    Transaction,
)


# Canonical Vanderplan CSV column order (export writes it; import reads it).
CSV_COLUMNS = ["date", "account", "payee", "category", "amount", "memo", "cleared", "is_income"]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _owned(model, request, **kwargs):
    """get_object_or_404 that always enforces ownership."""
    return get_object_or_404(model, user=request.user, **kwargs)


def _parse_month(request) -> date:
    """Read ?month=YYYY-MM, defaulting to the current month (day 1)."""
    raw = request.GET.get("month")
    if raw:
        try:
            return datetime.strptime(raw, "%Y-%m").date().replace(day=1)
        except ValueError:
            pass
    return services.month_floor(date.today())


def _month_param(month_start: date) -> str:
    return month_start.strftime("%Y-%m")


# --------------------------------------------------------------------------
# Registration (self-service signup)
# --------------------------------------------------------------------------
def register(request):
    """Create an account, seed a starter budget, and sign the user in."""
    if not settings.ALLOW_REGISTRATION:
        messages.error(request, "Registration is currently disabled.")
        return redirect("login")
    if request.user.is_authenticated:
        return redirect("dashboard")

    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        starter.create_starter_categories(user)
        login(request, user)
        messages.success(request, "Welcome! Your starter budget is ready.")
        return redirect("dashboard")
    return render(request, "registration/register.html", {"form": form})


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------
@login_required
def dashboard(request):
    month_start = _parse_month(request)
    groups = services.build_budget_groups(request.user, month_start)
    rows = [row for group in groups for row in group["rows"]]

    assigned_this_month = sum((r["assigned"] for r in rows), Decimal("0.00"))
    due_now_rows = [r for r in rows if r["status"] == "Due now"]
    underfunded_rows = [r for r in rows if r["status"] == "Underfunded"]
    overspent_rows = [r for r in rows if r["status"] == "Overspent"]

    upcoming_goals = (
        Goal.objects.filter(user=request.user, is_active=True, due_date__isnull=False)
        .select_related("category")
        .order_by("due_date")[:5]
    )
    recent_transactions = (
        Transaction.objects.filter(user=request.user)
        .select_related("account", "category")[:8]
    )

    context = {
        "month_start": month_start,
        "month_param": _month_param(month_start),
        "prev_month": _month_param(services.add_months(month_start, -1)),
        "next_month": _month_param(services.add_months(month_start, 1)),
        "total_cash": services.total_cash_available(request.user),
        "income_this_month": services.income_for_month(request.user, month_start),
        "assigned_this_month": assigned_this_month,
        "to_be_assigned": services.to_be_assigned(request.user, month_start),
        "bills_due_total": sum(
            (r["needed_this_month"] for r in due_now_rows), Decimal("0.00")
        ),
        "bills_due_count": len(due_now_rows),
        "underfunded_count": len(underfunded_rows),
        "overspent_count": len(overspent_rows),
        "attention_rows": due_now_rows + overspent_rows + underfunded_rows,
        "upcoming_goals": upcoming_goals,
        "recent_transactions": recent_transactions,
    }
    return render(request, "budget/dashboard.html", context)


# --------------------------------------------------------------------------
# Budget month screen
# --------------------------------------------------------------------------
@login_required
def budget_month(request):
    month_start = _parse_month(request)
    groups = services.build_budget_groups(request.user, month_start)
    context = {
        "month_start": month_start,
        "month_param": _month_param(month_start),
        "prev_month": _month_param(services.add_months(month_start, -1)),
        "next_month": _month_param(services.add_months(month_start, 1)),
        "groups": groups,
        "to_be_assigned": services.to_be_assigned(request.user, month_start),
        "total_cash": services.total_cash_available(request.user),
        "income_this_month": services.income_for_month(request.user, month_start),
    }
    return render(request, "budget/budget_month.html", context)


@login_required
def budget_assign(request):
    """Set the assigned amount for one category in one month."""
    if request.method != "POST":
        return redirect("budget_month")

    month_start = _parse_month(request)
    category = _owned(Category, request, pk=request.POST.get("category"))
    try:
        amount = Decimal(request.POST.get("assigned_amount", "0") or "0")
    except (InvalidOperation, TypeError):
        messages.error(request, "Enter a valid amount.")
        return redirect(f"{reverse('budget_month')}?month={_month_param(month_start)}")

    budget_month_obj = services.get_or_create_budget_month(request.user, month_start)
    assignment, _ = BudgetAssignment.objects.get_or_create(
        user=request.user, budget_month=budget_month_obj, category=category
    )
    assignment.assigned_amount = amount
    assignment.save(update_fields=["assigned_amount", "updated_at"])
    messages.success(request, f"Updated {category.name}.")
    return redirect(f"{reverse('budget_month')}?month={_month_param(month_start)}")


@login_required
def budget_move(request):
    """Move assigned money from one category to another within a month."""
    month_start = _parse_month(request)
    redirect_url = f"{reverse('budget_month')}?month={_month_param(month_start)}"
    if request.method != "POST":
        return redirect(redirect_url)

    from_category = _owned(Category, request, pk=request.POST.get("from_category"))
    to_category = _owned(Category, request, pk=request.POST.get("to_category"))
    if from_category == to_category:
        messages.error(request, "Choose two different categories.")
        return redirect(redirect_url)
    try:
        amount = Decimal(request.POST.get("amount", "0") or "0")
    except (InvalidOperation, TypeError):
        messages.error(request, "Enter a valid amount.")
        return redirect(redirect_url)
    if amount <= 0:
        messages.error(request, "Enter an amount greater than zero.")
        return redirect(redirect_url)

    services.move_between_categories(
        request.user, month_start, from_category, to_category, amount
    )
    messages.success(
        request, f"Moved ${amount} from {from_category.name} to {to_category.name}."
    )
    return redirect(redirect_url)


@login_required
def budget_fund(request):
    """One-click: assign the still-needed amount to a single category."""
    if request.method != "POST":
        return redirect("budget_month")
    month_start = _parse_month(request)
    category = _owned(Category, request, pk=request.POST.get("category"))
    added = services.fund_category(request.user, category, month_start)
    if added > 0:
        messages.success(request, f"Funded {category.name} with ${added}.")
    else:
        messages.info(request, f"{category.name} is already on track.")
    return redirect(f"{reverse('budget_month')}?month={_month_param(month_start)}")


@login_required
def budget_fund_all(request):
    """One-click: fund every category that is still short this month."""
    if request.method != "POST":
        return redirect("budget_month")
    month_start = _parse_month(request)
    groups = services.build_budget_groups(request.user, month_start)
    total = Decimal("0.00")
    count = 0
    for group in groups:
        for row in group["rows"]:
            if row["needed_this_month"] > 0:
                total += services.fund_category(
                    request.user, row["category"], month_start
                )
                count += 1
    if count:
        messages.success(
            request,
            f"Funded {count} categor{'y' if count == 1 else 'ies'} totalling ${total}.",
        )
    else:
        messages.info(request, "Everything is already funded.")
    return redirect(f"{reverse('budget_month')}?month={_month_param(month_start)}")


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------
@login_required
def reports(request):
    month_start = _parse_month(request)
    spending = services.spending_by_category(request.user, month_start)
    trend = services.monthly_trend(request.user, 6)
    networth = services.net_worth_trend(request.user, 6)

    # Bar widths (percent) computed here so the template carries no math.
    trend_max = max(
        [t["income"] for t in trend] + [t["spending"] for t in trend] + [Decimal("1")]
    )
    for t in trend:
        t["income_w"] = int(t["income"] / trend_max * 100)
        t["spending_w"] = int(t["spending"] / trend_max * 100)

    nw_max = max([abs(n["net_worth"]) for n in networth] + [Decimal("1")])
    for n in networth:
        n["width"] = int(abs(n["net_worth"]) / nw_max * 100)
        n["negative"] = n["net_worth"] < 0

    context = {
        "month_start": month_start,
        "month_param": _month_param(month_start),
        "prev_month": _month_param(services.add_months(month_start, -1)),
        "next_month": _month_param(services.add_months(month_start, 1)),
        "spending": spending,
        "trend": trend,
        "networth": networth,
        "income_this_month": services.income_for_month(request.user, month_start),
        "spending_this_month": services.total_spending_for_month(request.user, month_start),
        "current_net_worth": networth[-1]["net_worth"] if networth else Decimal("0.00"),
    }
    return render(request, "budget/reports.html", context)


# --------------------------------------------------------------------------
# Accounts
# --------------------------------------------------------------------------
@login_required
def account_list(request):
    accounts = Account.objects.filter(user=request.user)
    return render(
        request,
        "budget/account_list.html",
        {
            "accounts": accounts,
            "total_cash": services.total_cash_available(request.user),
        },
    )


@login_required
def account_create(request):
    form = AccountForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        account = form.save(commit=False)
        account.user = request.user
        account.save()
        messages.success(request, "Account created.")
        return redirect("account_list")
    return render(request, "budget/form.html", {"form": form, "title": "New Account"})


@login_required
def account_edit(request, pk):
    account = _owned(Account, request, pk=pk)
    form = AccountForm(request.POST or None, instance=account)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Account updated.")
        return redirect("account_list")
    return render(request, "budget/form.html", {"form": form, "title": "Edit Account"})


@login_required
def account_archive(request, pk):
    account = _owned(Account, request, pk=pk)
    if request.method == "POST":
        account.is_active = not account.is_active
        account.save(update_fields=["is_active", "updated_at"])
        messages.success(
            request, f"Account {'archived' if not account.is_active else 'reactivated'}."
        )
    return redirect("account_list")


# --------------------------------------------------------------------------
# Category groups & categories
# --------------------------------------------------------------------------
@login_required
def category_list(request):
    groups = (
        CategoryGroup.objects.filter(user=request.user)
        .prefetch_related("categories")
        .order_by("sort_order", "name")
    )
    return render(request, "budget/category_list.html", {"groups": groups})


@login_required
def group_create(request):
    form = CategoryGroupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        group = form.save(commit=False)
        group.user = request.user
        group.save()
        messages.success(request, "Category group created.")
        return redirect("category_list")
    return render(request, "budget/form.html", {"form": form, "title": "New Category Group"})


@login_required
def group_edit(request, pk):
    group = _owned(CategoryGroup, request, pk=pk)
    form = CategoryGroupForm(request.POST or None, instance=group)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Category group updated.")
        return redirect("category_list")
    return render(request, "budget/form.html", {"form": form, "title": "Edit Category Group"})


@login_required
def category_create(request):
    form = CategoryForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        category = form.save(commit=False)
        category.user = request.user
        category.save()
        messages.success(request, "Category created.")
        return redirect("category_list")
    return render(request, "budget/form.html", {"form": form, "title": "New Category"})


@login_required
def category_edit(request, pk):
    category = _owned(Category, request, pk=pk)
    form = CategoryForm(request.POST or None, instance=category, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Category updated.")
        return redirect("category_list")
    return render(request, "budget/form.html", {"form": form, "title": "Edit Category"})


@login_required
def category_detail(request, pk):
    category = _owned(Category, request, pk=pk)
    current = services.month_floor(date.today())
    row = services.build_category_row(request.user, category, current)
    history = services.category_history(request.user, category, 6)

    transactions = Transaction.objects.filter(
        user=request.user, category=category
    ).select_related("account")
    month = request.GET.get("month")
    if month:
        try:
            start = datetime.strptime(month, "%Y-%m").date().replace(day=1)
            transactions = transactions.filter(
                date__gte=start, date__lt=services.next_month_start(start)
            )
        except ValueError:
            month = None

    return render(
        request,
        "budget/category_detail.html",
        {
            "category": category,
            "row": row,
            "history": history,
            "transactions": transactions[:200],
            "month_filter": month,
        },
    )


@login_required
def category_toggle_hidden(request, pk):
    category = _owned(Category, request, pk=pk)
    if request.method == "POST":
        category.is_hidden = not category.is_hidden
        category.save(update_fields=["is_hidden", "updated_at"])
        messages.success(request, "Category visibility updated.")
    return redirect("category_list")


# --------------------------------------------------------------------------
# Transactions
# --------------------------------------------------------------------------
def _filtered_transactions(request):
    """Shared transaction filtering for the list and the CSV export."""
    transactions = Transaction.objects.filter(user=request.user).select_related(
        "account", "category"
    )
    account_id = request.GET.get("account")
    category_id = request.GET.get("category")
    month = request.GET.get("month")
    uncategorised = request.GET.get("uncategorised")
    income_only = request.GET.get("income")

    if account_id:
        transactions = transactions.filter(account_id=account_id)
    if income_only:
        transactions = transactions.filter(is_income=True)
    elif uncategorised:
        transactions = transactions.filter(category__isnull=True, is_income=False)
    elif category_id:
        transactions = transactions.filter(category_id=category_id)
    if month:
        try:
            start = datetime.strptime(month, "%Y-%m").date().replace(day=1)
            transactions = transactions.filter(
                date__gte=start, date__lt=services.next_month_start(start)
            )
        except ValueError:
            month = None

    filters = {
        "account": account_id,
        "category": category_id,
        "month": month,
        "uncategorised": uncategorised,
        "income": income_only,
    }
    return transactions, filters


@login_required
def transaction_list(request):
    transactions, filters = _filtered_transactions(request)
    return render(
        request,
        "budget/transaction_list.html",
        {
            "transactions": transactions[:300],
            "accounts": Account.objects.filter(user=request.user),
            "categories": Category.objects.filter(user=request.user, is_active=True),
            "filters": filters,
        },
    )


@login_required
def transaction_export(request):
    """Stream the filtered transactions as the canonical Vanderplan CSV."""
    transactions, _ = _filtered_transactions(request)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="transactions-{date.today():%Y%m%d}.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(CSV_COLUMNS)
    if request.GET.get("template"):
        return response  # header-only blank template
    for txn in transactions.iterator():
        writer.writerow(
            [
                txn.date.isoformat(),
                txn.account.name,
                txn.payee,
                txn.category.name if txn.category else "",
                f"{txn.amount:.2f}",
                txn.memo,
                "1" if txn.cleared else "0",
                "1" if txn.is_income else "0",
            ]
        )
    return response


@login_required
def transaction_import(request):
    """Import transactions from a CSV: upload -> preview -> commit."""
    MAX_BYTES = 2 * 1024 * 1024
    MAX_ROWS = 5000

    # Step 3: the user confirmed the previewed import.
    if request.method == "POST" and request.POST.get("confirm"):
        account = _owned(Account, request, pk=request.POST.get("account"))
        skip_duplicates = request.POST.get("skip_duplicates") == "1"
        text = request.POST.get("csv_text", "")
        rows = csv_io.analyze_csv(text, request.user, account)
        created = skipped = 0
        with db_transaction.atomic():
            for row in rows:
                if row["status"] != "ok":
                    continue
                if row["duplicate"] and skip_duplicates:
                    skipped += 1
                    continue
                Transaction.objects.create(
                    user=request.user, account=account, date=row["date"],
                    amount=row["amount"], payee=row["payee"], memo=row["memo"],
                    category=row["category"], cleared=row["cleared"],
                    is_income=row["is_income"],
                )
                created += 1
        msg = f"Imported {created} transaction{'' if created == 1 else 's'}."
        if skipped:
            msg += f" Skipped {skipped} duplicate{'' if skipped == 1 else 's'}."
        messages.success(request, msg)
        return redirect("transaction_list")

    # Step 2: a file was uploaded -> parse and show a preview.
    form = CsvImportForm(request.POST or None, request.FILES or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["csv_file"]
        if upload.size > MAX_BYTES:
            messages.error(request, "File too large (max 2 MB).")
            return redirect("transaction_import")
        text = upload.read().decode("utf-8-sig", errors="replace")
        account = form.cleaned_data["account"]
        rows = csv_io.analyze_csv(text, request.user, account)
        if len(rows) > MAX_ROWS:
            messages.error(request, f"Too many rows (max {MAX_ROWS}).")
            return redirect("transaction_import")
        summary = {
            "importable": sum(1 for r in rows if r["status"] == "ok" and not r["duplicate"]),
            "duplicate": sum(1 for r in rows if r["duplicate"]),
            "error": sum(1 for r in rows if r["status"] == "error"),
            "unmatched": sum(
                1 for r in rows
                if r["status"] == "ok" and r["category_name"] and not r["category_matched"]
            ),
        }
        return render(
            request,
            "budget/transaction_import.html",
            {
                "preview": True,
                "rows": rows,
                "summary": summary,
                "csv_text": text,
                "account": account,
                "skip_duplicates": form.cleaned_data["skip_duplicates"],
            },
        )

    # Step 1: show the upload form.
    return render(request, "budget/transaction_import.html", {"form": form})


@login_required
def transaction_create(request):
    initial = {}
    if request.GET.get("category"):
        initial["category"] = request.GET["category"]
    form = TransactionForm(request.POST or None, user=request.user, initial=initial)
    if request.method == "POST" and form.is_valid():
        txn = form.save(commit=False)
        txn.user = request.user
        txn.save()
        messages.success(request, "Transaction added.")
        return redirect("transaction_list")
    return render(request, "budget/form.html", {"form": form, "title": "New Transaction"})


@login_required
def income_create(request):
    """Add money to Ready to Assign via a dedicated inflow form."""
    form = IncomeForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        txn = form.save(commit=False)
        txn.user = request.user
        txn.is_income = True
        txn.category = None
        txn.amount = abs(txn.amount)
        txn.save()
        messages.success(request, f"Added ${txn.amount} to Ready to Assign.")
        return redirect("dashboard")
    return render(
        request,
        "budget/form.html",
        {"form": form, "title": "Add Income", "subtitle": "Goes straight to Ready to Assign."},
    )


@login_required
def transaction_edit(request, pk):
    txn = _owned(Transaction, request, pk=pk)
    form = TransactionForm(request.POST or None, instance=txn, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Transaction updated.")
        return redirect("transaction_list")
    return render(request, "budget/form.html", {"form": form, "title": "Edit Transaction"})


@login_required
def transaction_delete(request, pk):
    txn = _owned(Transaction, request, pk=pk)
    if request.method == "POST":
        txn.delete()
        messages.success(request, "Transaction deleted.")
        return redirect("transaction_list")
    return render(
        request,
        "budget/confirm_delete.html",
        {"object": txn, "title": "Delete Transaction", "cancel_url": "transaction_list"},
    )


# --------------------------------------------------------------------------
# Goals
# --------------------------------------------------------------------------
@login_required
def goal_list(request):
    month_start = services.month_floor(date.today())
    goals = (
        Goal.objects.filter(user=request.user)
        .select_related("category")
        .order_by("-is_active", "due_date")
    )
    rows = []
    for goal in goals:
        available = services.category_available(request.user, goal.category, month_start)
        pct = services.funded_percent(available, goal.target_amount)
        rows.append(
            {
                "goal": goal,
                "available": available,
                "needed_this_month": services.needed_this_month(
                    goal, available, month_start
                ),
                "funded_percent": pct,
                "funded_percent_bar": max(Decimal("0"), pct),
            }
        )
    return render(request, "budget/goal_list.html", {"rows": rows})


@login_required
def goal_create(request):
    form = GoalForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        goal = form.save(commit=False)
        goal.user = request.user
        goal.save()
        messages.success(request, "Goal created.")
        return redirect("goal_list")
    return render(request, "budget/form.html", {"form": form, "title": "New Goal"})


@login_required
def goal_edit(request, pk):
    goal = _owned(Goal, request, pk=pk)
    form = GoalForm(request.POST or None, instance=goal, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Goal updated.")
        return redirect("goal_list")
    return render(request, "budget/form.html", {"form": form, "title": "Edit Goal"})


@login_required
def goal_deactivate(request, pk):
    goal = _owned(Goal, request, pk=pk)
    if request.method == "POST":
        goal.is_active = not goal.is_active
        goal.save(update_fields=["is_active", "updated_at"])
        messages.success(request, "Goal updated.")
    return redirect("goal_list")


@login_required
def goal_advance(request, pk):
    goal = _owned(Goal, request, pk=pk)
    if request.method == "POST":
        if goal.is_repeating:
            services.advance_goal(goal)
            messages.success(
                request, f"Goal advanced. Next due {goal.due_date:%d %b %Y}."
            )
        else:
            messages.error(request, "This goal does not repeat.")
    return redirect("goal_list")
