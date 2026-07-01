"""Tests for self-service registration."""

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from budget.models import Category, CategoryGroup

User = get_user_model()
from budget.models import Budget


class RegistrationTests(TestCase):
    def test_register_page_renders(self):
        resp = self.client.get(reverse("register"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Create an account")

    def test_register_creates_user_logs_in_and_seeds_starter(self):
        resp = self.client.post(
            reverse("register"),
            {
                "username": "newbie",
                "email": "newbie@example.com",
                "password1": "sup3r-secret-pw",
                "password2": "sup3r-secret-pw",
            },
        )
        self.assertRedirects(resp, reverse("dashboard"))
        user = User.objects.get(username="newbie")
        # Logged in (session carries the user id).
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        # Starter budget created and owned by the new user only.
        self.assertEqual(CategoryGroup.objects.filter(user=user).count(), 4)
        self.assertTrue(Category.objects.filter(user=user, name="Groceries").exists())

    def test_duplicate_username_rejected(self):
        User.objects.create_user("taken", password="pw")
        resp = self.client.post(
            reverse("register"),
            {"username": "taken", "password1": "sup3r-secret-pw",
             "password2": "sup3r-secret-pw"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(User.objects.filter(username="taken").count(), 1)

    def test_password_mismatch_rejected(self):
        resp = self.client.post(
            reverse("register"),
            {"username": "mismatch", "password1": "sup3r-secret-pw",
             "password2": "different-pw"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(User.objects.filter(username="mismatch").exists())

    def test_authenticated_user_redirected_away(self):
        User.objects.create_user("already", password="pw")
        self.client.login(username="already", password="pw")
        resp = self.client.get(reverse("register"))
        self.assertRedirects(resp, reverse("dashboard"))

    @override_settings(ALLOW_REGISTRATION=False)
    def test_registration_can_be_disabled(self):
        resp = self.client.get(reverse("register"))
        self.assertRedirects(resp, reverse("login"))
        resp = self.client.post(
            reverse("register"),
            {"username": "blocked", "password1": "sup3r-secret-pw",
             "password2": "sup3r-secret-pw"},
        )
        self.assertFalse(User.objects.filter(username="blocked").exists())

    def test_login_page_shows_register_link(self):
        resp = self.client.get(reverse("login"))
        self.assertContains(resp, reverse("register"))

    @override_settings(ALLOW_REGISTRATION=False)
    def test_login_page_hides_link_when_disabled(self):
        resp = self.client.get(reverse("login"))
        self.assertNotContains(resp, reverse("register"))
