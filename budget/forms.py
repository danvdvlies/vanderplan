"""Forms for budgeting CRUD. Querysets that reference other user-owned models
are scoped to the logged-in user in __init__ so a user can never attach their
data to another user's records."""

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import Account, Category, CategoryGroup, Goal, Transaction


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

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["category_group"].queryset = CategoryGroup.objects.filter(
                user=user, is_active=True
            )


class TransactionForm(BootstrapModelForm):
    class Meta:
        model = Transaction
        fields = [
            "account", "date", "payee", "amount",
            "category", "memo", "cleared", "is_income",
        ]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["account"].queryset = Account.objects.filter(
                user=user, is_active=True
            )
            self.fields["category"].queryset = Category.objects.filter(
                user=user, is_active=True
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

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["account"].queryset = Account.objects.filter(
                user=user, is_active=True
            )
        self.fields["payee"].label = "Source"
        self.fields["amount"].help_text = "Enter a positive amount."

    def clean_amount(self):
        amount = self.cleaned_data.get("amount")
        if amount is None or amount <= 0:
            raise forms.ValidationError("Income must be a positive amount.")
        return amount


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

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user is not None:
            self.fields["category"].queryset = Category.objects.filter(
                user=user, is_active=True
            )
