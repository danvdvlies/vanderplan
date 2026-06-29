"""Optional development seed data.

Usage:
    python manage.py seed_data --user dan
Creates the user (with a default password) if it does not exist, then loads a
sample budget: two accounts, four category groups, seven categories, and a
repeating $220 car-registration goal due this month.
"""

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from budget.models import Account, Category, CategoryGroup, Goal


class Command(BaseCommand):
    help = "Load sample budgeting data for development."

    def add_arguments(self, parser):
        parser.add_argument("--user", default="demo", help="Username to attach data to.")
        parser.add_argument(
            "--password", default="budget123", help="Password if the user is created."
        )

    def handle(self, *args, **options):
        User = get_user_model()
        username = options["user"]
        user, created = User.objects.get_or_create(
            username=username, defaults={"email": f"{username}@example.com"}
        )
        if created:
            user.set_password(options["password"])
            user.save()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Created user '{username}' with password '{options['password']}'."
                )
            )

        # Accounts
        accounts = {
            "Everyday Account": Account.EVERYDAY,
            "Savings Account": Account.SAVINGS,
        }
        for name, acct_type in accounts.items():
            Account.objects.get_or_create(
                user=user,
                name=name,
                defaults={"account_type": acct_type, "starting_balance": Decimal("0.00")},
            )

        # Groups and their categories
        layout = [
            ("Immediate Obligations", 1, ["Rent", "Groceries", "Fuel"]),
            ("True Expenses", 2, ["Car Registration", "Car Service"]),
            ("Savings Goals", 3, ["Emergency Fund"]),
            ("Quality of Life", 4, ["Spending Money"]),
        ]
        categories = {}
        for group_name, order, cat_names in layout:
            group, _ = CategoryGroup.objects.get_or_create(
                user=user, name=group_name, defaults={"sort_order": order}
            )
            for i, cat_name in enumerate(cat_names, start=1):
                cat, _ = Category.objects.get_or_create(
                    user=user,
                    category_group=group,
                    name=cat_name,
                    defaults={"sort_order": i},
                )
                categories[cat_name] = cat

        # Example goal: Car Registration, $220, due this month, repeats quarterly
        today = date.today()
        Goal.objects.get_or_create(
            user=user,
            category=categories["Car Registration"],
            name="Car Registration",
            defaults={
                "goal_type": Goal.NEEDED_FOR_SPENDING,
                "target_amount": Decimal("220.00"),
                "due_date": today,
                "repeat_interval_months": 3,
            },
        )

        self.stdout.write(self.style.SUCCESS(f"Seed data ready for '{username}'."))
