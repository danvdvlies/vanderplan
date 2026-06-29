from django.contrib import admin

from .models import (
    Account,
    BudgetAssignment,
    BudgetMonth,
    Category,
    CategoryGroup,
    Goal,
    Transaction,
)


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "account_type", "starting_balance", "is_active")
    list_filter = ("account_type", "is_active")
    search_fields = ("name",)


@admin.register(CategoryGroup)
class CategoryGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "sort_order", "is_active")
    list_filter = ("is_active",)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "category_group", "sort_order", "is_hidden")
    list_filter = ("is_active", "is_hidden")
    search_fields = ("name",)


@admin.register(BudgetMonth)
class BudgetMonthAdmin(admin.ModelAdmin):
    list_display = ("month_start", "user")
    list_filter = ("month_start",)


@admin.register(BudgetAssignment)
class BudgetAssignmentAdmin(admin.ModelAdmin):
    list_display = ("category", "budget_month", "assigned_amount", "user")


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("date", "payee", "amount", "category", "account", "cleared", "user")
    list_filter = ("cleared", "date")
    search_fields = ("payee", "memo")


@admin.register(Goal)
class GoalAdmin(admin.ModelAdmin):
    list_display = (
        "category",
        "goal_type",
        "target_amount",
        "due_date",
        "repeat_interval_months",
        "is_active",
        "user",
    )
    list_filter = ("goal_type", "is_active")
