"""Tests for the read-only reports aggregates."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from budget import services
from budget.models import Account, Category, CategoryGroup, Transaction

User = get_user_model()


class ReportsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="pw")
        self.account = Account.objects.create(
            user=self.user, name="Everyday", starting_balance=Decimal("100.00")
        )
        self.group = CategoryGroup.objects.create(user=self.user, name="Group")
        self.groceries = Category.objects.create(
            user=self.user, category_group=self.group, name="Groceries"
        )
        self.fuel = Category.objects.create(
            user=self.user, category_group=self.group, name="Fuel"
        )
        self.month = services.month_floor(date.today())

    def _txn(self, amount, category=None, is_income=False, when=None):
        Transaction.objects.create(
            user=self.user, account=self.account, date=when or self.month,
            amount=Decimal(amount), category=category, is_income=is_income,
        )

    def test_spending_by_category_groups_and_totals(self):
        self._txn("-60.00", self.groceries)
        self._txn("-40.00", self.groceries)
        self._txn("-25.00", self.fuel)
        report = services.spending_by_category(self.user, self.month)
        self.assertEqual(report["total"], Decimal("125.00"))
        # Largest first: Groceries 100, Fuel 25
        self.assertEqual(report["rows"][0]["name"], "Groceries")
        self.assertEqual(report["rows"][0]["spent"], Decimal("100.00"))
        self.assertEqual(report["rows"][0]["percent"], Decimal("80"))
        self.assertEqual(report["rows"][1]["name"], "Fuel")

    def test_spending_excludes_income_and_inflows(self):
        self._txn("-30.00", self.groceries)
        self._txn("2000.00", is_income=True)        # income
        self._txn("15.00", self.groceries)          # a refund (positive)
        report = services.spending_by_category(self.user, self.month)
        self.assertEqual(report["total"], Decimal("30.00"))

    def test_uncategorised_expense_is_bucketed(self):
        self._txn("-12.00")  # no category, not income
        report = services.spending_by_category(self.user, self.month)
        self.assertEqual(report["rows"][0]["name"], "Uncategorised")
        self.assertEqual(report["rows"][0]["spent"], Decimal("12.00"))

    def test_total_spending_for_month(self):
        self._txn("-30.00", self.groceries)
        self._txn("-20.00", self.fuel)
        self.assertEqual(
            services.total_spending_for_month(self.user, self.month), Decimal("50.00")
        )

    def test_monthly_trend_window_and_values(self):
        self._txn("1000.00", is_income=True)
        self._txn("-200.00", self.groceries)
        trend = services.monthly_trend(self.user, 6)
        self.assertEqual(len(trend), 6)
        current = trend[-1]  # oldest first, so last is this month
        self.assertEqual(current["month"], self.month)
        self.assertEqual(current["income"], Decimal("1000.00"))
        self.assertEqual(current["spending"], Decimal("200.00"))
        self.assertEqual(current["net"], Decimal("800.00"))

    def test_net_worth_includes_starting_and_credit_card_debt(self):
        Account.objects.create(
            user=self.user, name="Visa", account_type=Account.CREDIT_CARD,
            starting_balance=Decimal("-50.00"),
        )
        self._txn("-30.00", self.groceries)
        nw = services.net_worth_trend(self.user, 6)[-1]["net_worth"]
        # 100 (everyday) - 50 (visa) - 30 (spend) = 20
        self.assertEqual(nw, Decimal("20.00"))

    def test_reports_view_renders(self):
        self.client.login(username="alice", password="pw")
        resp = self.client.get(reverse("reports"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Net worth")

    def test_reports_requires_login(self):
        resp = self.client.get(reverse("reports"))
        self.assertEqual(resp.status_code, 302)
