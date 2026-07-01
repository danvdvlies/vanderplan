"""Tests for multiple budgets: switching, isolation, and management."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from budget.models import Budget, Category, CategoryGroup

User = get_user_model()


class BudgetManagementTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="pw")
        self.default = Budget.objects.create(
            owner=self.user, name="Household", is_default=True
        )
        self.client.login(username="alice", password="pw")

    def test_new_budget_seeds_starter_and_switches(self):
        resp = self.client.post(reverse("budget_new"), {"name": "Emma's budget"})
        self.assertRedirects(resp, reverse("dashboard"))
        emma = Budget.objects.get(owner=self.user, name="Emma's budget")
        self.assertEqual(CategoryGroup.objects.filter(budget=emma).count(), 4)
        self.assertEqual(self.client.session["active_budget_id"], emma.pk)

    def test_switch_isolates_data(self):
        other = Budget.objects.create(owner=self.user, name="Other")
        g1 = CategoryGroup.objects.create(budget=self.default, name="G1")
        Category.objects.create(budget=self.default, category_group=g1, name="AlphaCat")
        g2 = CategoryGroup.objects.create(budget=other, name="G2")
        Category.objects.create(budget=other, category_group=g2, name="BetaCat")

        # Active = default -> sees AlphaCat only.
        page = self.client.get(reverse("budget_month"))
        self.assertContains(page, "AlphaCat")
        self.assertNotContains(page, "BetaCat")

        # Switch -> sees BetaCat only.
        self.client.post(reverse("budget_switch", args=[other.pk]))
        page = self.client.get(reverse("budget_month"))
        self.assertContains(page, "BetaCat")
        self.assertNotContains(page, "AlphaCat")

    def test_cannot_switch_to_other_users_budget(self):
        bob = User.objects.create_user("bob", password="pw")
        bob_budget = Budget.objects.create(owner=bob, name="Bob", is_default=True)
        resp = self.client.post(reverse("budget_switch", args=[bob_budget.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_cannot_delete_only_budget(self):
        resp = self.client.post(reverse("budget_delete", args=[self.default.pk]))
        self.assertRedirects(resp, reverse("budget_list"))
        self.assertTrue(Budget.objects.filter(pk=self.default.pk).exists())

    def test_delete_one_of_several(self):
        extra = Budget.objects.create(owner=self.user, name="Extra")
        resp = self.client.post(reverse("budget_delete", args=[extra.pk]))
        self.assertRedirects(resp, reverse("budget_list"))
        self.assertFalse(Budget.objects.filter(pk=extra.pk).exists())

    def test_set_default_moves_the_flag(self):
        extra = Budget.objects.create(owner=self.user, name="Extra")
        self.client.post(reverse("budget_set_default", args=[extra.pk]))
        self.default.refresh_from_db()
        extra.refresh_from_db()
        self.assertFalse(self.default.is_default)
        self.assertTrue(extra.is_default)

    def test_registration_creates_a_budget(self):
        self.client.logout()
        self.client.post(
            reverse("register"),
            {"username": "newbie", "password1": "sup3r-secret-pw",
             "password2": "sup3r-secret-pw"},
        )
        newbie = User.objects.get(username="newbie")
        budget = Budget.objects.get(owner=newbie)
        self.assertTrue(budget.is_default)
        self.assertEqual(CategoryGroup.objects.filter(budget=budget).count(), 4)
