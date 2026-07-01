"""Forms for budgeting CRUD. Querysets that reference other budget-owned models
are scoped to the active budget in __init__ so a user can never attach their
data to another budget's records."""

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import (
    Account,
    Budget,
    Category,
    CategoryGroup,
    Goal,
    Scenario,
    ScenarioLine,
    Transaction,
)


class RegisterForm(UserCreationForm):
    """Self-service signup: username + optional email + password."""

    email = forms.EmailField(required=False)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ["username", "email"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class BudgetForm(forms.ModelForm):
    class Meta:
        model = Budget
        fields = ["name"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["name"].widget.attrs.setdefault("class", "form-control")


class BootstrapModelForm(forms.ModelForm):
    """Applies Bootstrap form-control / form-select / form-check classes."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            else:
                widget.attrs.setdefault("class", "form-control")


class AccountForm(BootstrapModelForm):
    class Meta:
        model = Account
        fields = ["name", "account_type", "starting_balance", "is_active"]


class CategoryGroupForm(BootstrapModelForm):
    class Meta:
        model = CategoryGroup
        fields = ["name", "sort_order", "is_active"]


class CategoryForm(BootstrapModelForm):
    class Meta:
        model = Category
        fields = ["category_group", "name", "sort_order", "is_active", "is_hidden"]

    def __init__(self, *args, budget=None, **kwargs):
        super().__init__(*args, **kwargs)
        if budget is not None:
            self.fields["category_group"].queryset = CategoryGroup.objects.filter(
                budget=budget, is_active=True
            )


class TransactionForm(BootstrapModelForm):
    class Meta:
        model = Transaction
        fields = [
            "account", "date", "payee", "amount",
            "category", "memo", "cleared", "is_income",
        ]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, budget=None, **kwargs):
        super().__init__(*args, **kwargs)
        if budget is not None:
            self.fields["account"].queryset = Account.objects.filter(
                budget=budget, is_active=True
            )
            self.fields["category"].queryset = Category.objects.filter(
                budget=budget, is_active=True
            )
        self.fields["category"].required = False
        self.fields["category"].empty_label = "Uncategorised"
        self.fields["is_income"].label = "Income (goes to Ready to Assign)"

    def clean(self):
        cleaned = super().clean()
        # Income is never tied to a spending category; it funds the budget.
        if cleaned.get("is_income"):
            cleaned["category"] = None
        return cleaned


class IncomeForm(BootstrapModelForm):
    """Streamlined inflow form. Always saves a positive, uncategorised income."""

    class Meta:
        model = Transaction
        fields = ["account", "date", "payee", "amount", "memo"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, budget=None, **kwargs):
        super().__init__(*args, **kwargs)
        if budget is not None:
            self.fields["account"].queryset = Account.objects.filter(
                budget=budget, is_active=True
            )
        self.fields["payee"].label = "Source"
        self.fields["amount"].help_text = "Enter a positive amount."

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if amount is None or amount <= 0:
            raise forms.ValidationError("Income must be a positive amount.")
        return amount


class CsvImportForm(forms.Form):
    account = forms.ModelChoiceField(
        queryset=Account.objects.none(),
        help_text="Imported transactions are attached to this account.",
    )
    csv_file = forms.FileField(label="CSV file")
    skip_duplicates = forms.BooleanField(
        required=False, initial=True,
        help_text="Skip rows matching an existing date + amount + payee on this account.",
    )

    def __init__(self, *args, budget=None, **kwargs):
        super().__init__(*args, **kwargs)
        if budget is not None:
            self.fields["account"].queryset = Account.objects.filter(
                budget=budget, is_active=True
            )
        self.fields["account"].widget.attrs.setdefault("class", "form-select")
        self.fields["csv_file"].widget.attrs.setdefault("class", "form-control")
        self.fields["skip_duplicates"].widget.attrs.setdefault("class", "form-check-input")


class GoalForm(BootstrapModelForm):
    class Meta:
        model = Goal
        fields = [
            "category",
            "name",
            "goal_type",
            "target_amount",
            "due_date",
            "repeat_interval_months",
            "is_active",
        ]
        widgets = {"due_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, budget=None, **kwargs):
        super().__init__(*args, **kwargs)
        if budget is not None:
            self.fields["category"].queryset = Category.objects.filter(
                budget=budget, is_active=True
            )


class ScenarioForm(BootstrapModelForm):
    class Meta:
        model = Scenario
        fields = ["name", "notes", "monthly_income_override", "is_active"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}


class ScenarioLineForm(BootstrapModelForm):
    class Meta:
        model = ScenarioLine
        fields = ["label", "kind", "amount", "category", "replaces_current"]

    def __init__(self, *args, budget=None, **kwargs):
        super().__init__(*args, **kwargs)
        if budget is not None:
            self.fields["category"].queryset = Category.objects.filter(
                budget=budget, is_active=True
            )
        self.fields["category"].required = False
        self.fields["category"].empty_label = "— none —"
        self.fields["category"].help_text = "Optional: link a monthly expense to a current category."
        self.fields["replaces_current"].label = "Replaces the linked category's current cost"

    def clean(self):
        cleaned = super().clean()
        # 'replaces current' only makes sense for an expense tied to a category.
        if cleaned.get("replaces_current"):
            if cleaned.get("kind") != ScenarioLine.EXPENSE or not cleaned.get("category"):
                cleaned["replaces_current"] = False
        return cleaned
