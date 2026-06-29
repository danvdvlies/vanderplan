"""Case 9: a user must never see or reach another user's data."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from budget.models import Account, Category, CategoryGroup

User = get_user_model()


class OwnershipTests(TestCase):
    def setUp(self):
        self.alice = User.objects.create_user("alice", password="pw")
        self.bob = User.objects.create_user("bob", password="pw")
        self.bob_account = Account.objects.create(
            user=self.bob, name="Bob secret", starting_balance=Decimal("999.00")
        )
        group = CategoryGroup.objects.create(user=self.bob, name="Bob group")
        self.bob_category = Category.objects.create(
            user=self.bob, category_group=group, name="Bob category"
        )

    def test_login_required_redirects_anonymous(self):
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp["Location"])

    def test_account_list_only_shows_own(self):
        self.client.login(username="alice", password="pw")
        resp = self.client.get(reverse("account_list"))
        self.assertNotContains(resp, "Bob secret")

    def test_cannot_edit_other_users_account(self):
        self.client.login(username="alice", password="pw")
        resp = self.client.get(reverse("account_edit", args=[self.bob_account.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_cannot_assign_to_other_users_category(self):
        self.client.login(username="alice", password="pw")
        resp = self.client.post(
            reverse("budget_assign"),
            {"category": self.bob_category.pk, "assigned_amount": "50.00"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_total_cash_is_per_user(self):
        from budget import services

        self.assertEqual(services.total_cash_available(self.alice), Decimal("0.00"))
        self.assertEqual(services.total_cash_available(self.bob), Decimal("999.00"))
