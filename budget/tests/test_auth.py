"""Tests for password change and reset flows."""

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class PasswordChangeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("alice", password="old-pw-123456")
        self.client.login(username="alice", password="old-pw-123456")

    def test_change_password(self):
        resp = self.client.post(
            reverse("password_change"),
            {
                "old_password": "old-pw-123456",
                "new_password1": "brand-new-pw-987",
                "new_password2": "brand-new-pw-987",
            },
        )
        self.assertRedirects(resp, reverse("password_change_done"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("brand-new-pw-987"))

    def test_change_page_renders(self):
        self.assertEqual(self.client.get(reverse("password_change")).status_code, 200)


class PasswordResetTests(TestCase):
    def test_reset_sends_email_and_flows(self):
        User.objects.create_user("bob", email="bob@example.com", password="pw12345678")
        # Request the reset.
        resp = self.client.post(reverse("password_reset"), {"email": "bob@example.com"})
        self.assertRedirects(resp, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("bob@example.com", mail.outbox[0].to)

    def test_reset_form_and_login_pages_render(self):
        self.assertEqual(self.client.get(reverse("password_reset")).status_code, 200)
        login = self.client.get(reverse("login"))
        self.assertContains(login, reverse("password_reset"))  # "Forgot password?" link
