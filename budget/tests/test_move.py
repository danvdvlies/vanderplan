"""Tests for moving money between categories."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from budget import services
from budget.models import Account, BudgetAssignment, Category, CategoryGroup, Transaction

User = get_user_model()
from budget.models import Budget


class MoveMoneyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="pw")
        self.user_budget = Budget.objects.create(owner=self.user, is_default=True)
        self.account = Account.objects.create(budget=self.user_budget, name="Everyday")
        self.group = CategoryGroup.objects.create(budget=self.user_budget, name="Group")
        self.groceries = Category.objects.create(
            budget=self.user_budget, category_group=self.group, name="Groceries"
        )
        self.dining = Category.objects.create(
            budget=self.user_budget, category_group=self.group, name="Dining Out"
        )
        self.month = services.month_floor(date.today())

    def _assign(self, category, amount):
        bm = services.get_or_create_budget_month(self.user_budget, self.month)
        BudgetAssignment.objects.update_or_create(
            budget=self.user_budget, budget_month=bm, category=category,
            defaults={"assigned_amount": Decimal(amount)},
        )

    def _available(self, category):
        return services.category_available(self.user_budget, category, self.month)

    def test_move_shifts_available_between_categories(self):
        self._assign(self.dining, "100.00")
        services.move_between_categories(
            self.user_budget, self.month, self.dining, self.groceries, Decimal("40.00")
        )
        self.assertEqual(self._available(self.dining), Decimal("60.00"))
        self.assertEqual(self._available(self.groceries), Decimal("40.00"))

    def test_move_can_cover_an_overspent_category(self):
        # Groceries overspent by 30; Dining has 100 spare.
        self._assign(self.dining, "100.00")
        Transaction.objects.create(
            budget=self.user_budget, account=self.account, date=self.month,
            amount=Decimal("-30.00"), category=self.groceries,
        )
        self.assertEqual(self._available(self.groceries), Decimal("-30.00"))
        services.move_between_categories(
            self.user_budget, self.month, self.dining, self.groceries, Decimal("30.00")
        )
        self.assertEqual(self._available(self.groceries), Decimal("0.00"))
        self.assertEqual(self._available(self.dining), Decimal("70.00"))

    def test_move_leaves_to_be_assigned_unchanged(self):
        Transaction.objects.create(
            budget=self.user_budget, account=self.account, date=self.month,
            amount=Decimal("500.00"), category=None,
        )
        self._assign(self.dining, "100.00")
        before = services.to_be_assigned(self.user_budget, self.month)
        services.move_between_categories(
            self.user_budget, self.month, self.dining, self.groceries, Decimal("40.00")
        )
        self.assertEqual(services.to_be_assigned(self.user_budget, self.month), before)

    def test_move_out_can_make_source_assignment_negative(self):
        # No prior assignment on source: moving out drives it negative (allowed).
        services.move_between_categories(
            self.user_budget, self.month, self.dining, self.groceries, Decimal("25.00")
        )
        bm = services.get_or_create_budget_month(self.user_budget, self.month)
        src = BudgetAssignment.objects.get(
            budget=self.user_budget, budget_month=bm, category=self.dining
        )
        self.assertEqual(src.assigned_amount, Decimal("-25.00"))

    # --- view-level validation & ownership ---------------------------------
    def test_view_moves_money(self):
        self._assign(self.dining, "100.00")
        self.client.login(username="alice", password="pw")
        self.client.post(
            reverse("budget_move"),
            {"from_category": self.dining.pk, "to_category": self.groceries.pk,
             "amount": "40.00"},
        )
        self.assertEqual(self._available(self.groceries), Decimal("40.00"))

    def test_view_rejects_same_category(self):
        self._assign(self.dining, "100.00")
        self.client.login(username="alice", password="pw")
        self.client.post(
            reverse("budget_move"),
            {"from_category": self.dining.pk, "to_category": self.dining.pk,
             "amount": "10.00"},
        )
        self.assertEqual(self._available(self.dining), Decimal("100.00"))

    def test_view_rejects_non_positive_amount(self):
        self._assign(self.dining, "100.00")
        self.client.login(username="alice", password="pw")
        self.client.post(
            reverse("budget_move"),
            {"from_category": self.dining.pk, "to_category": self.groceries.pk,
             "amount": "0"},
        )
        self.assertEqual(self._available(self.dining), Decimal("100.00"))
        self.assertEqual(self._available(self.groceries), Decimal("0.00"))

    def test_view_cannot_move_to_other_users_category(self):
        bob = User.objects.create_user("bob", password="pw")
        bob_budget = Budget.objects.create(owner=bob, is_default=True)
        bob_cat = Category.objects.create(
            budget=bob_budget,
            category_group=CategoryGroup.objects.create(budget=bob_budget, name="G"),
            name="Bob cat",
        )
        self.client.login(username="alice", password="pw")
        resp = self.client.post(
            reverse("budget_move"),
            {"from_category": self.dining.pk, "to_category": bob_cat.pk,
             "amount": "10.00"},
        )
        self.assertEqual(resp.status_code, 404)
