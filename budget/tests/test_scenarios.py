"""Tests for the scenario planner (what-if affordability)."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from budget import services
from budget.models import (
    Account,
    Category,
    CategoryGroup,
    Scenario,
    ScenarioLine,
    Transaction,
)

User = get_user_model()


class ScenarioMathTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="pw")
        self.account = Account.objects.create(user=self.user, name="Everyday")
        self.group = CategoryGroup.objects.create(user=self.user, name="Group")
        self.rent = Category.objects.create(
            user=self.user, category_group=self.group, name="Rent"
        )
        self.month = services.month_floor(date.today())

    def _scenario(self, income_override="5000.00"):
        return Scenario.objects.create(
            user=self.user, name="New place",
            monthly_income_override=Decimal(income_override) if income_override else None,
        )

    def test_baseline_only_when_no_lines(self):
        s = self._scenario("5000.00")
        summary = services.scenario_summary(s)
        self.assertEqual(summary["base_income"], Decimal("5000.00"))
        self.assertEqual(summary["scenario_surplus"], summary["today_surplus"])
        self.assertTrue(summary["affordable"])

    def test_expense_line_reduces_surplus(self):
        s = self._scenario("5000.00")
        ScenarioLine.objects.create(
            user=self.user, scenario=s, label="Water", kind=ScenarioLine.EXPENSE,
            amount=Decimal("40.00"),
        )
        ScenarioLine.objects.create(
            user=self.user, scenario=s, label="NBN", kind=ScenarioLine.EXPENSE,
            amount=Decimal("80.00"),
        )
        summary = services.scenario_summary(s)
        self.assertEqual(summary["extra_expense"], Decimal("120.00"))
        self.assertEqual(summary["scenario_surplus"], Decimal("4880.00"))  # 5000 - 120

    def test_income_line_increases_surplus(self):
        s = self._scenario("5000.00")
        ScenarioLine.objects.create(
            user=self.user, scenario=s, label="Girls contribute",
            kind=ScenarioLine.INCOME, amount=Decimal("600.00"),
        )
        summary = services.scenario_summary(s)
        self.assertEqual(summary["scenario_income"], Decimal("5600.00"))
        self.assertEqual(summary["scenario_surplus"], Decimal("5600.00"))

    def test_one_off_is_upfront_not_monthly(self):
        s = self._scenario("5000.00")
        ScenarioLine.objects.create(
            user=self.user, scenario=s, label="Bond", kind=ScenarioLine.ONE_OFF,
            amount=Decimal("2400.00"),
        )
        summary = services.scenario_summary(s)
        self.assertEqual(summary["upfront"], Decimal("2400.00"))
        self.assertEqual(summary["scenario_surplus"], Decimal("5000.00"))  # unaffected monthly
        # surplus 5000/mo -> 1 month (ceil 0.48) to cover 2400
        self.assertEqual(summary["months_to_cover_upfront"], 1)

    def test_replaces_current_counts_only_the_delta(self):
        # Current rent averages 1800/mo over the last 3 months.
        for i in range(3):
            Transaction.objects.create(
                user=self.user, account=self.account,
                date=services.add_months(self.month, -i),
                amount=Decimal("-1800.00"), category=self.rent,
            )
        s = self._scenario("5000.00")
        ScenarioLine.objects.create(
            user=self.user, scenario=s, label="Rent (new place)",
            kind=ScenarioLine.EXPENSE, amount=Decimal("2400.00"),
            category=self.rent, replaces_current=True,
        )
        summary = services.scenario_summary(s)
        # delta = 2400 - 1800 = 600 added to outflow
        self.assertEqual(summary["extra_expense"], Decimal("600.00"))

    def test_unaffordable_flag(self):
        s = self._scenario("1000.00")
        ScenarioLine.objects.create(
            user=self.user, scenario=s, label="Rent", kind=ScenarioLine.EXPENSE,
            amount=Decimal("2400.00"),
        )
        summary = services.scenario_summary(s)
        self.assertFalse(summary["affordable"])
        self.assertEqual(summary["scenario_surplus"], Decimal("-1400.00"))

    def test_derived_income_baseline_used_without_override(self):
        Transaction.objects.create(
            user=self.user, account=self.account, date=self.month,
            amount=Decimal("3000.00"), is_income=True,
        )
        s = self._scenario(income_override=None)
        summary = services.scenario_summary(s)
        # 3000 over 3 months -> 1000/mo average
        self.assertEqual(summary["base_income"], Decimal("1000.00"))

    def test_scenario_does_not_touch_real_budget(self):
        s = self._scenario("5000.00")
        ScenarioLine.objects.create(
            user=self.user, scenario=s, label="Rent", kind=ScenarioLine.EXPENSE,
            amount=Decimal("2400.00"),
        )
        services.scenario_summary(s)
        # No transactions or assignments were created by planning.
        self.assertFalse(Transaction.objects.filter(user=self.user).exists())
        self.assertEqual(services.to_be_assigned(self.user, self.month), Decimal("0.00"))


class ScenarioViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="pw")
        self.client.login(username="alice", password="pw")

    def test_create_and_view_scenario(self):
        resp = self.client.post(
            reverse("scenario_create"),
            {"name": "Bigger place", "notes": "", "is_active": "on"},
        )
        scenario = Scenario.objects.get(user=self.user)
        self.assertRedirects(resp, reverse("scenario_detail", args=[scenario.pk]))
        page = self.client.get(reverse("scenario_detail", args=[scenario.pk]))
        self.assertContains(page, "Bigger place")

    def test_add_line_via_view(self):
        scenario = Scenario.objects.create(
            user=self.user, name="S", monthly_income_override=Decimal("5000")
        )
        self.client.post(
            reverse("scenario_line_create", args=[scenario.pk]),
            {"label": "Water", "kind": "expense", "amount": "40.00"},
        )
        self.assertEqual(scenario.lines.count(), 1)

    def test_cannot_view_other_users_scenario(self):
        bob = User.objects.create_user("bob", password="pw")
        bob_s = Scenario.objects.create(user=bob, name="Bob plan")
        resp = self.client.get(reverse("scenario_detail", args=[bob_s.pk]))
        self.assertEqual(resp.status_code, 404)
