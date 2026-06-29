"""Starter budget scaffolding shared by registration and the seed command.

Gives a brand-new user the envelope structure (groups + categories) so the
budget screen is usable immediately, without inventing fake accounts, goals or
transactions for them.
"""

from budget.models import Category, CategoryGroup

STARTER_LAYOUT = [
    ("Immediate Obligations", 1, ["Rent", "Groceries", "Fuel"]),
    ("True Expenses", 2, ["Car Registration", "Car Service"]),
    ("Savings Goals", 3, ["Emergency Fund"]),
    ("Quality of Life", 4, ["Spending Money"]),
]


def create_starter_categories(user) -> dict[str, Category]:
    """Create the default groups and categories for `user` (idempotent).

    Returns a mapping of category name -> Category for callers that want to
    attach extra data (e.g. the seed command's example goal).
    """
    categories: dict[str, Category] = {}
    for group_name, order, category_names in STARTER_LAYOUT:
        group, _ = CategoryGroup.objects.get_or_create(
            user=user, name=group_name, defaults={"sort_order": order}
        )
        for i, category_name in enumerate(category_names, start=1):
            category, _ = Category.objects.get_or_create(
                user=user,
                category_group=group,
                name=category_name,
                defaults={"sort_order": i},
            )
            categories[category_name] = category
    return categories
