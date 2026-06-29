"""Tests for clearing balances and reconciliation."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from budget import services
from budget.models import Account, Transaction

User = get_user_model()


class AccountBalancesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="pw")
        self.account = Account.objects.create(
            user=self.user, name="Everyday", starting_balance=Decimal("100.00")
        )

    def _txn(self, amount, cleared=False):
        return Transaction.objects.create(
            user=self.user, account=self.account, date=date(2026, 6, 10),
            amount=Decimal(amount), cleared=cleared,
        )

    def test_balance_breakdown(self):
        self._txn("-30.00", cleared=True)
        self._txn("-20.00", cleared=False)
        b = services.account_balances(self.account)
        self.assertEqual(b["working"], Decimal("50.00"))   # 100 - 30 - 20
        self.assertEqual(b["cleared"], Decimal("70.00"))   # 100 - 30
        self.assertEqual(b["uncleared"], Decimal("-20.00"))


class ReconcileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="pw")
        self.account = Account.objects.create(
            user=self.user, name="Everyday", starting_balance=Decimal("100.00")
        )

    def _txn(self, amount, cleared=True):
        return Transaction.objects.create(
            user=self.user, account=self.account, date=date(2026, 6, 10),
            amount=Decimal(amount), cleared=cleared,
        )

    def test_reconcile_matching_balance_locks_without_adjustment(self):
        self._txn("-40.00", cleared=True)  # cleared balance = 60
        result = services.reconcile_account(self.account, Decimal("60.00"), date(2026, 6, 30))
        self.assertEqual(result["difference"], Decimal("0.00"))
        self.assertIsNone(result["adjustment"])
        self.assertEqual(result["locked"], 1)
        self.assertTrue(Transaction.objects.get(amount=Decimal("-40.00")).reconciled)

    def test_reconcile_with_difference_creates_adjustment(self):
        self._txn("-40.00", cleared=True)  # cleared balance = 60
        result = services.reconcile_account(self.account, Decimal("75.00"), date(2026, 6, 30))
        self.assertEqual(result["difference"], Decimal("15.00"))
        adj = result["adjustment"]
        self.assertIsNotNone(adj)
        self.assertEqual(adj.amount, Decimal("15.00"))
        self.assertTrue(adj.cleared and adj.reconciled)
        # New cleared balance equals the statement.
        self.assertEqual(services.account_balances(self.account)["cleared"], Decimal("75.00"))

    def test_uncleared_transactions_not_locked(self):
        self._txn("-40.00", cleared=True)
        uncleared = self._txn("-10.00", cleared=False)
        services.reconcile_account(self.account, Decimal("60.00"), date(2026, 6, 30))
        uncleared.refresh_from_db()
        self.assertFalse(uncleared.reconciled)


class ReconcileViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="pw")
        self.account = Account.objects.create(
            user=self.user, name="Everyday", starting_balance=Decimal("100.00")
        )
        self.txn = Transaction.objects.create(
            user=self.user, account=self.account, date=date(2026, 6, 10),
            amount=Decimal("-40.00"), cleared=False,
        )
        self.client.login(username="alice", password="pw")

    def test_register_page_renders_balances(self):
        resp = self.client.get(reverse("account_register", args=[self.account.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Cleared balance")

    def test_toggle_cleared(self):
        self.client.post(reverse("transaction_toggle_cleared", args=[self.txn.pk]))
        self.txn.refresh_from_db()
        self.assertTrue(self.txn.cleared)

    def test_reconcile_via_view_locks_and_redirects(self):
        self.txn.cleared = True
        self.txn.save()
        resp = self.client.post(
            reverse("account_reconcile", args=[self.account.pk]),
            {"statement_balance": "60.00", "date": "2026-06-30"},
        )
        self.assertRedirects(resp, reverse("account_register", args=[self.account.pk]))
        self.txn.refresh_from_db()
        self.assertTrue(self.txn.reconciled)

    def test_reconciled_transaction_cannot_be_edited_or_deleted(self):
        self.txn.reconciled = True
        self.txn.save()
        edit = self.client.post(
            reverse("transaction_edit", args=[self.txn.pk]),
            {"account": self.account.pk, "date": "2026-06-10", "amount": "-99.00"},
        )
        self.assertRedirects(edit, reverse("transaction_list"))
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.amount, Decimal("-40.00"))  # unchanged
        delete = self.client.post(reverse("transaction_delete", args=[self.txn.pk]))
        self.assertRedirects(delete, reverse("transaction_list"))
        self.assertTrue(Transaction.objects.filter(pk=self.txn.pk).exists())

    def test_cannot_toggle_reconciled_transaction(self):
        self.txn.cleared = True
        self.txn.reconciled = True
        self.txn.save()
        self.client.post(reverse("transaction_toggle_cleared", args=[self.txn.pk]))
        self.txn.refresh_from_db()
        self.assertTrue(self.txn.cleared)  # still cleared, unchanged

    def test_cannot_reconcile_other_users_account(self):
        bob = User.objects.create_user("bob", password="pw")
        bob_acct = Account.objects.create(user=bob, name="Bob")
        resp = self.client.post(
            reverse("account_reconcile", args=[bob_acct.pk]),
            {"statement_balance": "0.00"},
        )
        self.assertEqual(resp.status_code, 404)
