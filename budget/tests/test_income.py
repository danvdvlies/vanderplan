"""Tests for explicit income / Ready to Assign."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from budget import services
from budget.models import Account, Category, CategoryGroup, Transaction

User = get_user_model()
from budget.models import Budget


class IncomeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="pw")
        self.user_budget = Budget.objects.create(owner=self.user, is_default=True)
        self.account = Account.objects.create(budget=self.user_budget, name="Everyday")
        self.group = CategoryGroup.objects.create(budget=self.user_budget, name="Group")
        self.category = Category.objects.create(
            budget=self.user_budget, category_group=self.group, name="Groceries"
        )
        self.month = services.month_floor(date.today())

    def test_income_for_month_sums_only_income(self):
        Transaction.objects.create(
            budget=self.user_budget, account=self.account, date=self.month,
            amount=Decimal("2000.00"), is_income=True,
        )
        Transaction.objects.create(  # a regular positive but not income
            budget=self.user_budget, account=self.account, date=self.month,
            amount=Decimal("50.00"), is_income=False,
        )
        self.assertEqual(
            services.income_for_month(self.user_budget, self.month), Decimal("2000.00")
        )

    def test_income_only_counts_its_own_month(self):
        Transaction.objects.create(
            budget=self.user_budget, account=self.account,
            date=services.add_months(self.month, -1),
            amount=Decimal("500.00"), is_income=True,
        )
        self.assertEqual(
            services.income_for_month(self.user_budget, self.month), Decimal("0.00")
        )

    def test_income_flows_into_ready_to_assign(self):
        Transaction.objects.create(
            budget=self.user_budget, account=self.account, date=self.month,
            amount=Decimal("1000.00"), is_income=True,
        )
        self.assertEqual(
            services.to_be_assigned(self.user_budget, self.month), Decimal("1000.00")
        )

    def test_income_create_view_saves_positive_uncategorised_income(self):
        self.client.login(username="alice", password="pw")
        resp = self.client.post(
            reverse("income_create"),
            {"account": self.account.pk, "date": self.month.isoformat(),
             "payee": "Employer", "amount": "1500.00", "memo": ""},
        )
        self.assertEqual(resp.status_code, 302)
        txn = Transaction.objects.get(budget=self.user_budget)
        self.assertTrue(txn.is_income)
        self.assertIsNone(txn.category)
        self.assertEqual(txn.amount, Decimal("1500.00"))

    def test_income_create_rejects_non_positive(self):
        self.client.login(username="alice", password="pw")
        resp = self.client.post(
            reverse("income_create"),
            {"account": self.account.pk, "date": self.month.isoformat(),
             "payee": "x", "amount": "0", "memo": ""},
        )
        self.assertEqual(resp.status_code, 200)  # re-rendered with errors
        self.assertFalse(Transaction.objects.exists())

    def test_transaction_form_clears_category_when_marked_income(self):
        from budget.forms import TransactionForm

        form = TransactionForm(
            data={
                "account": self.account.pk, "date": self.month.isoformat(),
                "payee": "Refund", "amount": "100.00",
                "category": self.category.pk, "is_income": "on",
            },
            budget=self.user_budget,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data["category"])

    def test_income_filter_on_transaction_list(self):
        Transaction.objects.create(
            budget=self.user_budget, account=self.account, date=self.month,
            amount=Decimal("900.00"), is_income=True, payee="Salary",
        )
        Transaction.objects.create(
            budget=self.user_budget, account=self.account, date=self.month,
            amount=Decimal("-20.00"), category=self.category, payee="Shop",
        )
        self.client.login(username="alice", password="pw")
        resp = self.client.get(reverse("transaction_list"), {"income": "1"})
        self.assertContains(resp, "Salary")
        self.assertNotContains(resp, "Shop")
