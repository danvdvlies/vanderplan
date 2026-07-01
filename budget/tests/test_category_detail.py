"""Tests for the category-detail drill-down."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from budget import services
from budget.models import Account, BudgetAssignment, Category, CategoryGroup, Transaction

User = get_user_model()
from budget.models import Budget


class CategoryDetailTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="pw")
        self.user_budget = Budget.objects.create(owner=self.user, is_default=True)
        self.account = Account.objects.create(budget=self.user_budget, name="Everyday")
        self.group = CategoryGroup.objects.create(budget=self.user_budget, name="Group")
        self.category = Category.objects.create(
            budget=self.user_budget, category_group=self.group, name="Groceries"
        )
        self.month = services.month_floor(date.today())

    def test_history_tracks_assigned_activity_available(self):
        bm = services.get_or_create_budget_month(self.user_budget, self.month)
        BudgetAssignment.objects.create(
            budget=self.user_budget, budget_month=bm, category=self.category,
            assigned_amount=Decimal("200.00"),
        )
        Transaction.objects.create(
            budget=self.user_budget, account=self.account, date=self.month,
            amount=Decimal("-50.00"), category=self.category,
        )
        history = services.category_history(self.user_budget, self.category, 6)
        self.assertEqual(len(history), 6)
        current = history[-1]
        self.assertEqual(current["month"], self.month)
        self.assertEqual(current["assigned"], Decimal("200.00"))
        self.assertEqual(current["activity"], Decimal("-50.00"))
        self.assertEqual(current["available"], Decimal("150.00"))

    def test_detail_page_renders_with_transactions(self):
        Transaction.objects.create(
            budget=self.user_budget, account=self.account, date=self.month,
            amount=Decimal("-50.00"), category=self.category, payee="Market",
        )
        self.client.login(username="alice", password="pw")
        resp = self.client.get(reverse("category_detail", args=[self.category.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Groceries")
        self.assertContains(resp, "Market")
        self.assertContains(resp, "Monthly history")

    def test_detail_only_shows_this_categorys_transactions(self):
        other = Category.objects.create(
            budget=self.user_budget, category_group=self.group, name="Fuel"
        )
        Transaction.objects.create(
            budget=self.user_budget, account=self.account, date=self.month,
            amount=Decimal("-10.00"), category=self.category, payee="InGroceries",
        )
        Transaction.objects.create(
            budget=self.user_budget, account=self.account, date=self.month,
            amount=Decimal("-99.00"), category=other, payee="InFuel",
        )
        self.client.login(username="alice", password="pw")
        resp = self.client.get(reverse("category_detail", args=[self.category.pk]))
        self.assertContains(resp, "InGroceries")
        self.assertNotContains(resp, "InFuel")

    def test_cannot_view_other_users_category(self):
        bob = User.objects.create_user("bob", password="pw")
        bob_budget = Budget.objects.create(owner=bob, is_default=True)
        bob_cat = Category.objects.create(
            budget=bob_budget,
            category_group=CategoryGroup.objects.create(budget=bob_budget, name="G"),
            name="Bob cat",
        )
        self.client.login(username="alice", password="pw")
        resp = self.client.get(reverse("category_detail", args=[bob_cat.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_add_transaction_prefills_category(self):
        self.client.login(username="alice", password="pw")
        resp = self.client.get(
            reverse("transaction_create"), {"category": self.category.pk}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["form"].initial.get("category"), str(self.category.pk))
