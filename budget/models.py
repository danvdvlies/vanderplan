"""
Data models for the zero-based budgeting app.

All budgeting data belongs to a `Budget` (scoping is by `budget`). Domain models
also keep a nullable `user` FK as the creator/audit reference. All money is
DecimalField — never float.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

# Two decimal places, room for large balances. Shared by all money fields.
MONEY = dict(max_digits=12, decimal_places=2)


class TimeStampedModel(models.Model):
    """Abstract base providing created_at / updated_at."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Budget(TimeStampedModel):
    """A budget container. All budgeting data belongs to a Budget.

    A user can own several budgets and switch between them. (Phase B adds
    membership so several users can share one budget.) Domain models keep a
    `user` FK as the creator/audit reference, but scoping is by `budget`.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="owned_budgets"
    )
    name = models.CharField(max_length=120)
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["owner", "is_default"])]

    def __str__(self):
        return self.name


class BudgetMembership(TimeStampedModel):
    """Which users can access a budget, and with what role.

    owner  — full access + manage members + rename/delete the budget
    editor — full access to the budgeting data (no member/budget management)
    viewer — read-only
    """

    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"
    ROLE_CHOICES = [(OWNER, "Owner"), (EDITOR, "Editor"), (VIEWER, "Viewer")]

    budget = models.ForeignKey(
        Budget, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="budget_memberships"
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=EDITOR)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )

    class Meta:
        ordering = ["role", "user__username"]
        constraints = [
            models.UniqueConstraint(
                fields=["budget", "user"], name="unique_budget_member"
            )
        ]
        indexes = [models.Index(fields=["user"])]

    def __str__(self):
        return f"{self.user} / {self.budget} ({self.role})"

    @property
    def can_edit(self):
        return self.role in (self.OWNER, self.EDITOR)


@receiver(post_save, sender=Budget)
def _ensure_owner_membership(sender, instance, created, **kwargs):
    """Every new budget grants its owner an owner-role membership."""
    if created:
        BudgetMembership.objects.get_or_create(
            budget=instance,
            user=instance.owner,
            defaults={"role": BudgetMembership.OWNER},
        )


class Account(TimeStampedModel):
    EVERYDAY = "everyday"
    SAVINGS = "savings"
    CASH = "cash"
    CREDIT_CARD = "credit_card"
    OTHER = "other"
    ACCOUNT_TYPES = [
        (EVERYDAY, "Everyday"),
        (SAVINGS, "Savings"),
        (CASH, "Cash"),
        (CREDIT_CARD, "Credit Card"),
        (OTHER, "Other"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE, related_name="accounts"
    )
    budget = models.ForeignKey(
        Budget, on_delete=models.CASCADE, related_name="accounts"
    )
    name = models.CharField(max_length=120)
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPES, default=EVERYDAY)
    starting_balance = models.DecimalField(default=Decimal("0.00"), **MONEY)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["budget", "is_active"])]

    def __str__(self):
        return self.name

    @property
    def current_balance(self):
        """starting_balance plus the sum of all transactions on this account.

        Derived rather than stored so it can never drift out of sync.
        """
        agg = self.transactions.aggregate(total=models.Sum("amount"))
        return self.starting_balance + (agg["total"] or Decimal("0.00"))

    @property
    def is_credit_card(self):
        return self.account_type == self.CREDIT_CARD


class CategoryGroup(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE, related_name="category_groups"
    )
    budget = models.ForeignKey(
        Budget, on_delete=models.CASCADE, related_name="category_groups"
    )
    name = models.CharField(max_length=120)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]
        indexes = [models.Index(fields=["budget", "sort_order"])]

    def __str__(self):
        return self.name


class Category(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE, related_name="categories"
    )
    budget = models.ForeignKey(
        Budget, on_delete=models.CASCADE, related_name="categories"
    )
    category_group = models.ForeignKey(
        CategoryGroup, on_delete=models.CASCADE, related_name="categories"
    )
    name = models.CharField(max_length=120)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    is_hidden = models.BooleanField(default=False)

    class Meta:
        ordering = ["sort_order", "name"]
        verbose_name_plural = "categories"
        indexes = [models.Index(fields=["budget", "category_group", "sort_order"])]

    def __str__(self):
        return self.name


class BudgetMonth(TimeStampedModel):
    """A single calendar month for a user. month_start is always day 1."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE, related_name="budget_months"
    )
    budget = models.ForeignKey(
        Budget, on_delete=models.CASCADE, related_name="budget_months"
    )
    month_start = models.DateField(help_text="First day of the month.")

    class Meta:
        ordering = ["month_start"]
        constraints = [
            models.UniqueConstraint(
                fields=["budget", "month_start"], name="unique_budget_month"
            )
        ]
        indexes = [models.Index(fields=["budget", "month_start"])]

    def __str__(self):
        return self.month_start.strftime("%B %Y")


class BudgetAssignment(TimeStampedModel):
    """Money assigned to a category for a given month."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE, related_name="assignments"
    )
    budget = models.ForeignKey(
        Budget, on_delete=models.CASCADE, related_name="assignments"
    )
    budget_month = models.ForeignKey(
        BudgetMonth, on_delete=models.CASCADE, related_name="assignments"
    )
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, related_name="assignments"
    )
    # Negative allowed so the user can move money back out of a category.
    assigned_amount = models.DecimalField(default=Decimal("0.00"), **MONEY)

    class Meta:
        ordering = ["category__sort_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["budget_month", "category"],
                name="unique_month_category",
            )
        ]
        indexes = [models.Index(fields=["budget", "budget_month"])]

    def __str__(self):
        return f"{self.category} / {self.budget_month}: {self.assigned_amount}"


class Transaction(TimeStampedModel):
    """A manual transaction. Expenses negative, income positive."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE, related_name="transactions"
    )
    budget = models.ForeignKey(
        Budget, on_delete=models.CASCADE, related_name="transactions"
    )
    account = models.ForeignKey(
        Account, on_delete=models.CASCADE, related_name="transactions"
    )
    date = models.DateField()
    payee = models.CharField(max_length=200, blank=True)
    amount = models.DecimalField(**MONEY)
    # Null category => "Uncategorised" (allowed temporarily).
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
    )
    memo = models.CharField(max_length=255, blank=True)
    cleared = models.BooleanField(default=False)
    # Locked once part of a completed reconciliation (read-only thereafter).
    reconciled = models.BooleanField(default=False)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    # Explicit inflow marker. Income lands in "Ready to Assign" (no spending
    # category) instead of being an ambiguous uncategorised positive amount.
    is_income = models.BooleanField(default=False)

    class Meta:
        ordering = ["-date", "-created_at"]
        indexes = [
            models.Index(fields=["budget", "date"]),
            models.Index(fields=["budget", "category", "date"]),
            models.Index(fields=["budget", "account", "date"]),
        ]

    def __str__(self):
        return f"{self.date} {self.payee} {self.amount}"


class Goal(TimeStampedModel):
    NEEDED_FOR_SPENDING = "needed_for_spending"
    SAVINGS_BALANCE = "savings_balance"
    MONTHLY_SAVINGS_BUILDER = "monthly_savings_builder"
    GOAL_TYPES = [
        (NEEDED_FOR_SPENDING, "Needed for spending"),
        (SAVINGS_BALANCE, "Savings balance"),
        (MONTHLY_SAVINGS_BUILDER, "Monthly savings builder"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE, related_name="goals"
    )
    budget = models.ForeignKey(
        Budget, on_delete=models.CASCADE, related_name="goals"
    )
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, related_name="goals"
    )
    name = models.CharField(max_length=120, blank=True)
    goal_type = models.CharField(
        max_length=30, choices=GOAL_TYPES, default=NEEDED_FOR_SPENDING
    )
    target_amount = models.DecimalField(default=Decimal("0.00"), **MONEY)
    due_date = models.DateField(null=True, blank=True)
    repeat_interval_months = models.PositiveIntegerField(
        null=True, blank=True, help_text="e.g. 3 for a quarterly bill. Blank = one-off."
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["due_date", "category__sort_order"]
        indexes = [models.Index(fields=["budget", "is_active", "due_date"])]

    def __str__(self):
        return self.name or f"Goal for {self.category}"

    @property
    def is_repeating(self):
        return bool(self.repeat_interval_months)


class Scenario(TimeStampedModel):
    """A what-if affordability scenario layered on the real budget.

    Scenarios are read-only over the real budget: they only *read* income and
    spending averages and never create accounts, transactions or assignments,
    so the actual budget is never affected.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE, related_name="scenarios"
    )
    budget = models.ForeignKey(
        Budget, on_delete=models.CASCADE, related_name="scenarios"
    )
    name = models.CharField(max_length=120)
    notes = models.TextField(blank=True)
    # Optional: override the derived monthly-income baseline with a fixed figure.
    monthly_income_override = models.DecimalField(
        null=True, blank=True,
        help_text="Leave blank to use your recent average monthly income.",
        **MONEY,
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["budget", "is_active"])]

    def __str__(self):
        return self.name


class ScenarioLine(TimeStampedModel):
    EXPENSE = "expense"
    INCOME = "income"
    ONE_OFF = "one_off"
    KIND_CHOICES = [
        (EXPENSE, "Monthly expense"),
        (INCOME, "Monthly income"),
        (ONE_OFF, "One-off upfront cost"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.CASCADE, related_name="scenario_lines"
    )
    budget = models.ForeignKey(
        Budget, on_delete=models.CASCADE, related_name="scenario_lines"
    )
    scenario = models.ForeignKey(
        Scenario, on_delete=models.CASCADE, related_name="lines"
    )
    label = models.CharField(max_length=120)
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=EXPENSE)
    # Magnitude (always positive): a monthly amount for expense/income, or a
    # total upfront amount for one_off.
    amount = models.DecimalField(default=Decimal("0.00"), **MONEY)
    # Optional link to a real category, for a monthly expense that replaces or
    # tops up a cost you already have.
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="scenario_lines",
    )
    # If True (expense lines only), the planner counts this amount minus the
    # category's current average monthly spend, so an increase isn't double-counted.
    replaces_current = models.BooleanField(default=False)

    class Meta:
        ordering = ["kind", "label"]
        indexes = [models.Index(fields=["budget", "scenario"])]

    def __str__(self):
        return f"{self.label} ({self.get_kind_display()})"
