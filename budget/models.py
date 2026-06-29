"""
Data models for the zero-based budgeting app.

Every user-owned model carries a `user` FK from day one so the app can become
multi-user without a migration scramble. All money is DecimalField — never float.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models

# Two decimal places, room for large balances. Shared by all money fields.
MONEY = dict(max_digits=12, decimal_places=2)


class TimeStampedModel(models.Model):
    """Abstract base providing created_at / updated_at."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


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
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="accounts"
    )
    name = models.CharField(max_length=120)
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPES, default=EVERYDAY)
    starting_balance = models.DecimalField(default=Decimal("0.00"), **MONEY)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["user", "is_active"])]

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
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="category_groups"
    )
    name = models.CharField(max_length=120)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]
        indexes = [models.Index(fields=["user", "sort_order"])]

    def __str__(self):
        return self.name


class Category(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="categories"
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
        indexes = [models.Index(fields=["user", "category_group", "sort_order"])]

    def __str__(self):
        return self.name


class BudgetMonth(TimeStampedModel):
    """A single calendar month for a user. month_start is always day 1."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="budget_months"
    )
    month_start = models.DateField(help_text="First day of the month.")

    class Meta:
        ordering = ["month_start"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "month_start"], name="unique_user_month"
            )
        ]
        indexes = [models.Index(fields=["user", "month_start"])]

    def __str__(self):
        return self.month_start.strftime("%B %Y")


class BudgetAssignment(TimeStampedModel):
    """Money assigned to a category for a given month."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assignments"
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
                fields=["user", "budget_month", "category"],
                name="unique_user_month_category",
            )
        ]
        indexes = [models.Index(fields=["user", "budget_month"])]

    def __str__(self):
        return f"{self.category} / {self.budget_month}: {self.assigned_amount}"


class Transaction(TimeStampedModel):
    """A manual transaction. Expenses negative, income positive."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="transactions"
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

    class Meta:
        ordering = ["-date", "-created_at"]
        indexes = [
            models.Index(fields=["user", "date"]),
            models.Index(fields=["user", "category", "date"]),
            models.Index(fields=["user", "account", "date"]),
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
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="goals"
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
        indexes = [models.Index(fields=["user", "is_active", "due_date"])]

    def __str__(self):
        return self.name or f"Goal for {self.category}"

    @property
    def is_repeating(self):
        return bool(self.repeat_interval_months)
