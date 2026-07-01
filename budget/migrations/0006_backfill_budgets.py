"""Give every existing user a default Budget and move all their data into it."""

from django.db import migrations

DOMAIN_MODELS = [
    "Account",
    "CategoryGroup",
    "Category",
    "BudgetMonth",
    "BudgetAssignment",
    "Transaction",
    "Goal",
    "Scenario",
    "ScenarioLine",
]


def forwards(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Budget = apps.get_model("budget", "Budget")
    models = {name: apps.get_model("budget", name) for name in DOMAIN_MODELS}

    for user in User.objects.all():
        # Reuse a budget if a previous partial run already made one.
        budget = Budget.objects.filter(owner=user).order_by("id").first()
        if budget is None:
            budget = Budget.objects.create(owner=user, name="My Budget", is_default=True)
        for model in models.values():
            model.objects.filter(user=user, budget__isnull=True).update(budget=budget)


def backwards(apps, schema_editor):
    Budget = apps.get_model("budget", "Budget")
    models = {name: apps.get_model("budget", name) for name in DOMAIN_MODELS}
    for model in models.values():
        model.objects.update(budget=None)
    Budget.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("budget", "0005_budget_and_more")]
    operations = [migrations.RunPython(forwards, backwards)]
