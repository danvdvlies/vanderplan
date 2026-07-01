"""Resolve the active budget (and the user's role in it) for each request.

Access is by membership: ``request.budget`` is a budget the user is a member of,
chosen from the session (falling back to their owned default). ``request.role``
and ``request.can_edit`` drive permission checks. A brand-new user with no
budget gets one created lazily (as owner).
"""

from .models import Budget, BudgetMembership


def accessible_budgets(user):
    return Budget.objects.filter(memberships__user=user).distinct()


def resolve_active(request):
    """Return (budget, role) for the active budget, or (None, None)."""
    user = request.user
    qs = accessible_budgets(user)

    budget = None
    budget_id = request.session.get("active_budget_id")
    if budget_id:
        budget = qs.filter(pk=budget_id).first()
    if budget is None:
        budget = qs.filter(owner=user, is_default=True).first() or qs.first()
    if budget is None:
        # No budget yet (e.g. a fresh superuser): create one they own.
        budget = Budget.objects.create(owner=user, name="My Budget", is_default=True)

    membership = BudgetMembership.objects.filter(budget=budget, user=user).first()
    role = membership.role if membership else None
    return budget, role


class ActiveBudgetMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.budget = None
        request.role = None
        request.can_edit = False
        request.is_owner = False
        if request.user.is_authenticated:
            request.budget, request.role = resolve_active(request)
            request.can_edit = request.role in (
                BudgetMembership.OWNER,
                BudgetMembership.EDITOR,
            )
            request.is_owner = request.role == BudgetMembership.OWNER
        return self.get_response(request)
