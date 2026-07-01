"""Tests for budget sharing: membership, roles, and read-only enforcement."""

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from budget.models import (
    Account,
    Budget,
    BudgetMembership,
    Category,
    CategoryGroup,
)

User = get_user_model()


class MembershipTests(TestCase):
    def test_creating_a_budget_grants_owner_membership(self):
        user = User.objects.create_user("alice", password="pw")
        budget = Budget.objects.create(owner=user, name="B", is_default=True)
        m = BudgetMembership.objects.get(budget=budget, user=user)
        self.assertEqual(m.role, BudgetMembership.OWNER)


class SharingTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("dad", password="pw")
        self.budget = Budget.objects.create(owner=self.owner, name="Household", is_default=True)
        self.group = CategoryGroup.objects.create(budget=self.budget, name="G")
        self.category = Category.objects.create(
            budget=self.budget, category_group=self.group, name="Groceries"
        )
        self.account = Account.objects.create(budget=self.budget, name="Everyday")
        self.viewer = User.objects.create_user("emma", password="pw")
        self.editor = User.objects.create_user("mia", password="pw")

    def _member(self, user, role):
        return BudgetMembership.objects.create(budget=self.budget, user=user, role=role)

    def test_owner_can_add_member_by_username(self):
        self.client.login(username="dad", password="pw")
        self.client.post(reverse("member_add"), {"username": "emma", "role": "viewer"})
        m = BudgetMembership.objects.get(budget=self.budget, user=self.viewer)
        self.assertEqual(m.role, "viewer")

    def test_non_owner_cannot_add_member(self):
        self._member(self.editor, BudgetMembership.EDITOR)
        # Editor's active budget is the shared one (they own none of their own... they do get one lazily,
        # so switch them onto the shared budget first).
        self.client.login(username="mia", password="pw")
        session = self.client.session
        session["active_budget_id"] = self.budget.pk
        session.save()
        resp = self.client.post(reverse("member_add"), {"username": "emma", "role": "viewer"})
        self.assertEqual(resp.status_code, 403)

    def test_shared_member_sees_the_budget_data(self):
        self._member(self.viewer, BudgetMembership.VIEWER)
        self.client.login(username="emma", password="pw")
        self.client.post(reverse("budget_switch", args=[self.budget.pk]))
        page = self.client.get(reverse("budget_month"))
        self.assertContains(page, "Groceries")

    def test_viewer_is_read_only(self):
        self._member(self.viewer, BudgetMembership.VIEWER)
        self.client.login(username="emma", password="pw")
        self.client.post(reverse("budget_switch", args=[self.budget.pk]))
        # A representative mutation is blocked.
        resp = self.client.post(
            reverse("budget_assign") + f"?month=2026-06",
            {"category": self.category.pk, "assigned_amount": "50.00"},
        )
        self.assertEqual(resp.status_code, 403)
        resp = self.client.get(reverse("account_create"))
        self.assertEqual(resp.status_code, 403)

    def test_editor_can_mutate(self):
        self._member(self.editor, BudgetMembership.EDITOR)
        self.client.login(username="mia", password="pw")
        self.client.post(reverse("budget_switch", args=[self.budget.pk]))
        resp = self.client.post(
            reverse("budget_assign") + "?month=2026-06",
            {"category": self.category.pk, "assigned_amount": "50.00"},
        )
        self.assertEqual(resp.status_code, 302)  # succeeded (redirect)

    def test_cannot_switch_to_budget_without_membership(self):
        stranger_budget = Budget.objects.create(
            owner=User.objects.create_user("bob", password="pw"), name="Bob"
        )
        self.client.login(username="emma", password="pw")
        resp = self.client.post(reverse("budget_switch", args=[stranger_budget.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_owner_can_change_and_remove_member(self):
        m = self._member(self.viewer, BudgetMembership.VIEWER)
        self.client.login(username="dad", password="pw")
        self.client.post(reverse("member_role", args=[m.pk]), {"role": "editor"})
        m.refresh_from_db()
        self.assertEqual(m.role, "editor")
        self.client.post(reverse("member_remove", args=[m.pk]))
        self.assertFalse(BudgetMembership.objects.filter(pk=m.pk).exists())

    def test_owner_membership_cannot_be_removed(self):
        owner_m = BudgetMembership.objects.get(budget=self.budget, user=self.owner)
        self.client.login(username="dad", password="pw")
        self.client.post(reverse("member_remove", args=[owner_m.pk]))
        self.assertTrue(BudgetMembership.objects.filter(pk=owner_m.pk).exists())
