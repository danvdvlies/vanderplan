"""Tests for CSV export and import."""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from budget import csv_io
from budget.models import Account, Category, CategoryGroup, Transaction

User = get_user_model()

HEADER = "date,account,payee,category,amount,memo,cleared,is_income\n"


class CsvExportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="pw")
        self.account = Account.objects.create(user=self.user, name="Everyday")
        self.other = Account.objects.create(user=self.user, name="Savings")
        self.group = CategoryGroup.objects.create(user=self.user, name="Group")
        self.cat = Category.objects.create(
            user=self.user, category_group=self.group, name="Groceries"
        )
        Transaction.objects.create(
            user=self.user, account=self.account, date=date(2026, 6, 10),
            amount=Decimal("-25.50"), category=self.cat, payee="Market",
        )
        Transaction.objects.create(
            user=self.user, account=self.other, date=date(2026, 6, 11),
            amount=Decimal("100.00"), payee="Other acct",
        )
        self.client.login(username="alice", password="pw")

    def test_export_includes_header_and_rows(self):
        resp = self.client.get(reverse("transaction_export"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        body = resp.content.decode()
        self.assertIn("date,account,payee,category,amount,memo,cleared,is_income", body)
        self.assertIn("Market", body)
        self.assertIn("-25.50", body)

    def test_export_respects_account_filter(self):
        resp = self.client.get(reverse("transaction_export"), {"account": self.account.pk})
        body = resp.content.decode()
        self.assertIn("Market", body)
        self.assertNotIn("Other acct", body)

    def test_template_download_is_header_only(self):
        resp = self.client.get(reverse("transaction_export"), {"template": "1"})
        body = resp.content.decode().strip()
        self.assertEqual(body, "date,account,payee,category,amount,memo,cleared,is_income")


class CsvAnalyzeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="pw")
        self.account = Account.objects.create(user=self.user, name="Everyday")
        self.group = CategoryGroup.objects.create(user=self.user, name="Group")
        self.cat = Category.objects.create(
            user=self.user, category_group=self.group, name="Groceries"
        )

    def test_classifies_ok_error_and_unmatched(self):
        text = (
            HEADER
            + "2026-06-10,Everyday,Market,Groceries,-25.50,,1,0\n"
            + "2026-06-11,Everyday,Pay,,2000.00,salary,0,1\n"      # income
            + "2026-06-12,Everyday,Shop,Nonexist,-9.00,,0,0\n"     # unmatched cat
            + "not-a-date,Everyday,Bad,Groceries,-1.00,,0,0\n"     # error
            + "2026-06-13,Everyday,Bad2,Groceries,xyz,,0,0\n"      # error amount
        )
        rows = csv_io.analyze_csv(text, self.user, self.account)
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["status"], "ok")
        self.assertEqual(rows[0]["category"], self.cat)
        self.assertTrue(rows[0]["cleared"])
        self.assertTrue(rows[1]["is_income"])
        self.assertIsNone(rows[1]["category"])
        self.assertFalse(rows[2]["category_matched"])  # unmatched -> uncategorised
        self.assertIsNone(rows[2]["category"])
        self.assertEqual(rows[3]["status"], "error")
        self.assertEqual(rows[4]["status"], "error")

    def test_duplicate_detection(self):
        Transaction.objects.create(
            user=self.user, account=self.account, date=date(2026, 6, 10),
            amount=Decimal("-25.50"), payee="Market",
        )
        text = HEADER + "2026-06-10,Everyday,Market,,-25.50,,0,0\n"
        rows = csv_io.analyze_csv(text, self.user, self.account)
        self.assertTrue(rows[0]["duplicate"])


class CsvImportViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="pw")
        self.account = Account.objects.create(user=self.user, name="Everyday")
        self.group = CategoryGroup.objects.create(user=self.user, name="Group")
        self.cat = Category.objects.create(
            user=self.user, category_group=self.group, name="Groceries"
        )
        self.client.login(username="alice", password="pw")

    def _upload(self, text):
        return SimpleUploadedFile("t.csv", text.encode(), content_type="text/csv")

    def test_preview_then_commit_creates_transactions(self):
        text = (
            HEADER
            + "2026-06-10,Everyday,Market,Groceries,-25.50,weekly,1,0\n"
            + "2026-06-11,Everyday,Pay,,2000.00,,0,1\n"
        )
        preview = self.client.post(
            reverse("transaction_import"),
            {"account": self.account.pk, "csv_file": self._upload(text), "skip_duplicates": "on"},
        )
        self.assertTrue(preview.context["preview"])
        self.assertEqual(preview.context["summary"]["importable"], 2)

        commit = self.client.post(
            reverse("transaction_import"),
            {"confirm": "1", "account": self.account.pk, "skip_duplicates": "1", "csv_text": text},
        )
        self.assertRedirects(commit, reverse("transaction_list"))
        self.assertEqual(Transaction.objects.filter(user=self.user).count(), 2)
        groceries = Transaction.objects.get(payee="Market")
        self.assertEqual(groceries.category, self.cat)
        self.assertTrue(groceries.cleared)
        self.assertTrue(Transaction.objects.get(payee="Pay").is_income)

    def test_commit_skips_duplicates_when_requested(self):
        Transaction.objects.create(
            user=self.user, account=self.account, date=date(2026, 6, 10),
            amount=Decimal("-25.50"), payee="Market",
        )
        text = HEADER + "2026-06-10,Everyday,Market,,-25.50,,0,0\n"
        self.client.post(
            reverse("transaction_import"),
            {"confirm": "1", "account": self.account.pk, "skip_duplicates": "1", "csv_text": text},
        )
        self.assertEqual(Transaction.objects.filter(payee="Market").count(), 1)

    def test_unmatched_category_imports_as_uncategorised(self):
        text = HEADER + "2026-06-10,Everyday,Shop,Nonexist,-9.00,,0,0\n"
        self.client.post(
            reverse("transaction_import"),
            {"confirm": "1", "account": self.account.pk, "skip_duplicates": "0", "csv_text": text},
        )
        txn = Transaction.objects.get(payee="Shop")
        self.assertIsNone(txn.category)

    def test_error_rows_are_not_imported(self):
        text = HEADER + "bad-date,Everyday,X,,-1.00,,0,0\n"
        self.client.post(
            reverse("transaction_import"),
            {"confirm": "1", "account": self.account.pk, "skip_duplicates": "0", "csv_text": text},
        )
        self.assertFalse(Transaction.objects.exists())

    def test_cannot_import_into_other_users_account(self):
        bob = User.objects.create_user("bob", password="pw")
        bob_acct = Account.objects.create(user=bob, name="Bob")
        text = HEADER + "2026-06-10,Bob,X,,-1.00,,0,0\n"
        resp = self.client.post(
            reverse("transaction_import"),
            {"confirm": "1", "account": bob_acct.pk, "skip_duplicates": "0", "csv_text": text},
        )
        self.assertEqual(resp.status_code, 404)
