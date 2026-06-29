"""Tests for the money template filter."""

from decimal import Decimal

from django.test import TestCase

from budget.templatetags.budget_extras import money


class MoneyFilterTests(TestCase):
    def test_positive(self):
        self.assertEqual(money(Decimal("45.2")), "$45.20")

    def test_negative_sign_before_dollar(self):
        self.assertEqual(money(Decimal("-45.20")), "-$45.20")

    def test_thousands_separator(self):
        self.assertEqual(money(Decimal("1234567.5")), "$1,234,567.50")
        self.assertEqual(money(Decimal("-1234.5")), "-$1,234.50")

    def test_zero(self):
        self.assertEqual(money(Decimal("0")), "$0.00")

    def test_none_and_blank(self):
        self.assertEqual(money(None), "$0.00")
        self.assertEqual(money(""), "$0.00")
