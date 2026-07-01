"""Tests for the one-click Fund buttons."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from budget import services
from budget.models import (
    Account,
    BudgetAssignment,
    Category,
    CategoryGroup,
    Goal,
)

User = get_user_model()
from budget.models import Budget


class FundingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="pw")
        self.user_budget = Budget.objects.create(owner=self.user, is_default=True)
        self.account = Account.objects.create(budget=self.user_budget, name="Everyday")
        self.group = CategoryGroup.objects.create(budget=self.user_budget, name="True Expenses")
        self.category = Category.objects.create(
            budget=self.user_budget, category_group=self.group, name="Car Registration"
        )
        self.month = services.month_floor(date.today())

    def _goal(self, due, target="220.00", repeat=3):
        return Goal.objects.create(
            budget=self.user_budget,
            category=self.category,
            target_amount=Decimal(target),
            due_date=due,
            repeat_interval_months=repeat,
        )

    def test_fund_due_now_assigns_full_shortfall(self):
        self._goal(self.month)  # due this month, $0 saved
        added = services.fund_category(self.user_budget, self.category, self.month)
        self.assertEqual(added, Decimal("220.00"))
        # Available now meets the target and nothing more is needed.
        self.assertEqual(
            services.category_available(self.user_budget, self.category, self.month),
            Decimal("220.00"),
        )
        row = services.build_category_row(self.user_budget, self.category, self.month)
        self.assertEqual(row["needed_this_month"], Decimal("0.00"))

    def test_fund_adds_to_existing_assignment(self):
        self._goal(self.month)
        bm = services.get_or_create_budget_month(self.user_budget, self.month)
        BudgetAssignment.objects.create(
            budget=self.user_budget, budget_month=bm, category=self.category,
            assigned_amount=Decimal("50.00"),
        )
        added = services.fund_category(self.user_budget, self.category, self.month)
        self.assertEqual(added, Decimal("170.00"))
        assignment = BudgetAssignment.objects.get(
            budget=self.user_budget, budget_month=bm, category=self.category
        )
        self.assertEqual(assignment.assigned_amount, Decimal("220.00"))

    def test_fund_future_goal_assigns_one_month_portion(self):
        self._goal(services.add_months(self.month, 3))  # 3 months out
        added = services.fund_category(self.user_budget, self.category, self.month)
        self.assertEqual(added, Decimal("73.34"))

    def test_fund_already_funded_does_nothing(self):
        self._goal(self.month)
        services.fund_category(self.user_budget, self.category, self.month)
        added_again = services.fund_category(self.user_budget, self.category, self.month)
        self.assertEqual(added_again, Decimal("0.00"))

    def test_fund_no_goal_does_nothing(self):
        added = services.fund_category(self.user_budget, self.category, self.month)
        self.assertEqual(added, Decimal("0.00"))

    def test_fund_view_requires_ownership(self):
        bob = User.objects.create_user("bob", password="pw")
        bob_budget = Budget.objects.create(owner=bob, is_default=True)
        bob_cat = Category.objects.create(
            budget=bob_budget,
            category_group=CategoryGroup.objects.create(budget=bob_budget, name="G"),
            name="Bob cat",
        )
        self.client.login(username="alice", password="pw")
        resp = self.client.post(reverse("budget_fund"), {"category": bob_cat.pk})
        self.assertEqual(resp.status_code, 404)

    def test_fund_all_funds_every_short_category(self):
        self._goal(self.month)  # Car Registration, needs 220
        groceries = Category.objects.create(
            budget=self.user_budget, category_group=self.group, name="Groceries"
        )
        Goal.objects.create(
            budget=self.user_budget, category=groceries,
            target_amount=Decimal("100.00"), due_date=self.month,
        )
        self.client.login(username="alice", password="pw")
        self.client.post(reverse("budget_fund_all"))
        self.assertEqual(
            services.build_category_row(self.user_budget, self.category, self.month)["needed_this_month"],
            Decimal("0.00"),
        )
        self.assertEqual(
            services.build_category_row(self.user_budget, groceries, self.month)["needed_this_month"],
            Decimal("0.00"),
        )
