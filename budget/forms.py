"""Forms for budgeting CRUD. Querysets that reference other user-owned models
are scoped to the logged-in user in __init__ so a user can never attach their
data to another user's records."""

from django import forms

from .models import Account, Category, CategoryGroup, Goal, Transaction


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
        fields = ["account", "date", "payee", "amount", "category", "memo", "cleared"]
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
