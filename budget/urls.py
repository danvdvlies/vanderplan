from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    # Budget month
    path("budget/", views.budget_month, name="budget_month"),
    path("budget/assign/", views.budget_assign, name="budget_assign"),
    path("budget/move/", views.budget_move, name="budget_move"),
    path("budget/fund/", views.budget_fund, name="budget_fund"),
    path("budget/fund-all/", views.budget_fund_all, name="budget_fund_all"),
    # Accounts
    path("accounts/", views.account_list, name="account_list"),
    path("accounts/new/", views.account_create, name="account_create"),
    path("accounts/<int:pk>/edit/", views.account_edit, name="account_edit"),
    path("accounts/<int:pk>/register/", views.account_register, name="account_register"),
    path("accounts/<int:pk>/reconcile/", views.account_reconcile, name="account_reconcile"),
    path("accounts/<int:pk>/archive/", views.account_archive, name="account_archive"),
    path(
        "transactions/<int:pk>/toggle-cleared/",
        views.transaction_toggle_cleared,
        name="transaction_toggle_cleared",
    ),
    # Category groups & categories
    path("categories/", views.category_list, name="category_list"),
    path("categories/<int:pk>/", views.category_detail, name="category_detail"),
    path("groups/new/", views.group_create, name="group_create"),
    path("groups/<int:pk>/edit/", views.group_edit, name="group_edit"),
    path("categories/new/", views.category_create, name="category_create"),
    path("categories/<int:pk>/edit/", views.category_edit, name="category_edit"),
    path(
        "categories/<int:pk>/toggle-hidden/",
        views.category_toggle_hidden,
        name="category_toggle_hidden",
    ),
    # Transactions
    path("transactions/", views.transaction_list, name="transaction_list"),
    path("transactions/export/", views.transaction_export, name="transaction_export"),
    path("transactions/import/", views.transaction_import, name="transaction_import"),
    path("transactions/new/", views.transaction_create, name="transaction_create"),
    path("income/new/", views.income_create, name="income_create"),
    path("transactions/<int:pk>/edit/", views.transaction_edit, name="transaction_edit"),
    path(
        "transactions/<int:pk>/delete/",
        views.transaction_delete,
        name="transaction_delete",
    ),
    # Goals
    # Scenario planner
    path("planning/", views.scenario_list, name="scenario_list"),
    path("planning/new/", views.scenario_create, name="scenario_create"),
    path("planning/<int:pk>/", views.scenario_detail, name="scenario_detail"),
    path("planning/<int:pk>/edit/", views.scenario_edit, name="scenario_edit"),
    path("planning/<int:pk>/delete/", views.scenario_delete, name="scenario_delete"),
    path("planning/<int:pk>/lines/add/", views.scenario_line_create, name="scenario_line_create"),
    path("planning/lines/<int:pk>/delete/", views.scenario_line_delete, name="scenario_line_delete"),
    # Reports
    path("reports/", views.reports, name="reports"),
    # Goals
    path("goals/", views.goal_list, name="goal_list"),
    path("goals/new/", views.goal_create, name="goal_create"),
    path("goals/<int:pk>/edit/", views.goal_edit, name="goal_edit"),
    path("goals/<int:pk>/deactivate/", views.goal_deactivate, name="goal_deactivate"),
    path("goals/<int:pk>/advance/", views.goal_advance, name="goal_advance"),
]
