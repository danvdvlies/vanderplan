"""Tests for moving money between categories."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from budget import services
from budget.models import Account, BudgetAssignment, Category, CategoryGroup, Transaction

User = get_user_model()


class MoveMoneyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="pw")
        self.account = Account.objects.create(user=self.user, name="Everyday")
        self.group = CategoryGroup.objects.create(user=self.user, name="Group")
        self.groceries = Category.objects.create(
            user=self.user, category_group=self.group, name="Groceries"
        )
        self.dining = Category.objects.create(
            user=self.user, category_group=self.group, name="Dining Out"
        )
        self.month = services.month_floor(date.today())

    def _assign(self, category, amount):
        bm = services.get_or_create_budget_month(self.user, self.month)
        BudgetAssignment.objects.update_or_create(
            user=self.user, budget_month=bm, category=category,
            defaults={"assigned_amount": Decimal(amount)},
        )

    def _available(self, category):
        return services.category_available(self.user, category, self.month)

    def test_move_shifts_available_between_categories(self):
        self._assign(self.dining, "100.00")
        services.move_between_categories(
            self.user, self.month, self.dining, self.groceries, Decimal("40.00")
        )
        self.assertEqual(self._available(self.dining), Decimal("60.00"))
        self.assertEqual(self._available(self.groceries), Decimal("40.00"))

    def test_move_can_cover_an_overspent_category(self):
        # Groceries overspent by 30; Dining has 100 spare.
        self._assign(self.dining, "100.00")
        Transaction.objects.create(
            user=self.user, account=self.account, date=self.month,
            amount=Decimal("-30.00"), category=self.groceries,
        )
        self.assertEqual(self._available(self.groceries), Decimal("-30.00"))
        services.move_between_categories(
            self.user, self.month, self.dining, self.groceries, Decimal("30.00")
        )
        self.assertEqual(self._available(self.groceries), Decimal("0.00"))
        self.assertEqual(self._available(self.dining), Decimal("70.00"))

    def test_move_leaves_to_be_assigned_unchanged(self):
        Transaction.objects.create(
            user=self.user, account=self.account, date=self.month,
            amount=Decimal("500.00"), category=None,
        )
        self._assign(self.dining, "100.00")
        before = services.to_be_assigned(self.user, self.month)
        services.move_between_categories(
            self.user, self.month, self.dining, self.groceries, Decimal("40.00")
        )
        self.assertEqual(services.to_be_assigned(self.user, self.month), before)

    def test_move_out_can_make_source_assignment_negative(self):
        # No prior assignment on source: moving out drives it negative (allowed).
        services.move_between_categories(
            self.user, self.month, self.dining, self.groceries, Decimal("25.00")
        )
        bm = services.get_or_create_budget_month(self.user, self.month)
        src = BudgetAssignment.objects.get(
            user=self.user, budget_month=bm, category=self.dining
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
        bob_cat = Category.objects.create(
            user=bob,
            category_group=CategoryGroup.objects.create(user=bob, name="G"),
            name="Bob cat",
        )
        self.client.login(username="alice", password="pw")
        resp = self.client.post(
            reverse("budget_move"),
            {"from_category": self.dining.pk, "to_category": bob_cat.pk,
             "amount": "10.00"},
        )
        self.assertEqual(resp.status_code, 404)
