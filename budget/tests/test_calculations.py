"""Tests for the core budgeting calculations (spec section 13, cases 1-8)."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from budget import services
from budget.models import (
    Account,
    BudgetAssignment,
    Category,
    CategoryGroup,
    Goal,
    Transaction,
)

User = get_user_model()


class BudgetingMixin:
    def setUp(self):
        self.user = User.objects.create_user("alice", password="x")
        self.account = Account.objects.create(
            user=self.user, name="Everyday", starting_balance=Decimal("0.00")
        )
        self.group = CategoryGroup.objects.create(user=self.user, name="True Expenses")
        self.category = Category.objects.create(
            user=self.user, category_group=self.group, name="Car Registration"
        )

    def assign(self, month_start, amount):
        bm = services.get_or_create_budget_month(self.user, month_start)
        BudgetAssignment.objects.create(
            user=self.user,
            budget_month=bm,
            category=self.category,
            assigned_amount=Decimal(amount),
        )

    def spend(self, on_date, amount):
        Transaction.objects.create(
            user=self.user,
            account=self.account,
            date=on_date,
            amount=Decimal(amount),
            category=self.category,
        )


class AvailableBalanceTests(BudgetingMixin, TestCase):
    def test_available_rolls_forward(self):
        """Case 1: previous month's available carries into the next month."""
        self.assign(date(2026, 1, 1), "100.00")
        # Nothing assigned/spent in Feb -> Feb available == Jan available.
        jan = services.category_available(self.user, self.category, date(2026, 1, 1))
        feb = services.category_available(self.user, self.category, date(2026, 2, 1))
        self.assertEqual(jan, Decimal("100.00"))
        self.assertEqual(feb, Decimal("100.00"))

    def test_expense_reduces_available(self):
        """Case 2: a spending transaction lowers available."""
        self.assign(date(2026, 1, 1), "100.00")
        self.spend(date(2026, 1, 15), "-30.00")
        available = services.category_available(self.user, self.category, date(2026, 1, 1))
        self.assertEqual(available, Decimal("70.00"))

    def test_assigned_increases_available(self):
        """Case 3: assigning money raises available."""
        self.assign(date(2026, 1, 1), "50.00")
        self.assign(date(2026, 2, 1), "100.00")
        # Feb: 50 (rolled) + 100 = 150
        feb = services.category_available(self.user, self.category, date(2026, 2, 1))
        self.assertEqual(feb, Decimal("150.00"))

    def test_spec_rollforward_example(self):
        """Spec section 7: 50 prev + 100 assigned - 30 spend = 120."""
        self.assign(date(2026, 1, 1), "50.00")
        self.assign(date(2026, 2, 1), "100.00")
        self.spend(date(2026, 2, 10), "-30.00")
        feb = services.category_available(self.user, self.category, date(2026, 2, 1))
        self.assertEqual(feb, Decimal("120.00"))


class NeededThisMonthTests(BudgetingMixin, TestCase):
    def _goal(self, due, target="220.00", repeat=3):
        return Goal.objects.create(
            user=self.user,
            category=self.category,
            target_amount=Decimal(target),
            due_date=due,
            repeat_interval_months=repeat,
        )

    def test_due_this_month_needs_full_shortfall(self):
        """Case 4: a goal due this month requires the full shortfall."""
        goal = self._goal(date(2026, 6, 15))
        needed = services.needed_this_month(goal, Decimal("0.00"), date(2026, 6, 1))
        self.assertEqual(needed, Decimal("220.00"))

    def test_due_in_future_divides_across_months(self):
        """Case 5 / criterion #11: $220 due 3 months out -> $73.34."""
        goal = self._goal(date(2026, 9, 15))
        needed = services.needed_this_month(goal, Decimal("0.00"), date(2026, 6, 1))
        self.assertEqual(needed, Decimal("73.34"))

    def test_overdue_needs_full_shortfall(self):
        """Case 6: an overdue goal requires the full shortfall."""
        goal = self._goal(date(2026, 3, 15))
        needed = services.needed_this_month(goal, Decimal("0.00"), date(2026, 6, 1))
        self.assertEqual(needed, Decimal("220.00"))

    def test_partial_available_reduces_needed(self):
        goal = self._goal(date(2026, 6, 15))
        needed = services.needed_this_month(goal, Decimal("70.00"), date(2026, 6, 1))
        self.assertEqual(needed, Decimal("150.00"))

    def test_fully_funded_needs_nothing(self):
        goal = self._goal(date(2026, 9, 15))
        needed = services.needed_this_month(goal, Decimal("220.00"), date(2026, 6, 1))
        self.assertEqual(needed, Decimal("0.00"))


class FundedPercentTests(TestCase):
    def test_funded_percent(self):
        """Case 7."""
        self.assertEqual(services.funded_percent(Decimal("110"), Decimal("220")), Decimal("50"))
        self.assertEqual(services.funded_percent(Decimal("220"), Decimal("220")), Decimal("100"))

    def test_funded_percent_capped_at_100(self):
        self.assertEqual(services.funded_percent(Decimal("500"), Decimal("220")), Decimal("100"))

    def test_zero_target_is_zero(self):
        self.assertEqual(services.funded_percent(Decimal("50"), Decimal("0")), Decimal("0"))


class RepeatingGoalTests(BudgetingMixin, TestCase):
    def test_advance_moves_due_date_by_interval(self):
        """Case 8: advancing adds repeat_interval_months to the due date."""
        goal = Goal.objects.create(
            user=self.user,
            category=self.category,
            target_amount=Decimal("220.00"),
            due_date=date(2026, 6, 28),
            repeat_interval_months=3,
        )
        services.advance_goal(goal)
        goal.refresh_from_db()
        self.assertEqual(goal.due_date, date(2026, 9, 28))

    def test_add_months_clamps_day(self):
        self.assertEqual(services.add_months(date(2026, 1, 31), 1), date(2026, 2, 28))


class ToBeAssignedTests(BudgetingMixin, TestCase):
    def test_to_be_assigned_reflects_unassigned_cash(self):
        # $300 income, $100 assigned to the category -> $200 to be assigned.
        Transaction.objects.create(
            user=self.user, account=self.account, date=date(2026, 6, 1),
            amount=Decimal("300.00"), category=None,
        )
        self.assign(date(2026, 6, 1), "100.00")
        tba = services.to_be_assigned(self.user, date(2026, 6, 1))
        self.assertEqual(tba, Decimal("200.00"))

    def test_credit_card_excluded_from_cash(self):
        Account.objects.create(
            user=self.user, name="Visa", account_type=Account.CREDIT_CARD,
            starting_balance=Decimal("-500.00"),
        )
        self.assertEqual(services.total_cash_available(self.user), Decimal("0.00"))
