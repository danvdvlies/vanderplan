"""Resolve the active budget for each authenticated request.

Sets ``request.budget`` so views and templates can scope to one budget. The
choice is held in the session; it falls back to the user's default budget, and
a brand-new user (e.g. created via ``createsuperuser``) gets one created lazily.
"""

from .models import Budget


def resolve_active_budget(request):
    user = request.user
    budget_id = request.session.get("active_budget_id")
    if budget_id:
        budget = Budget.objects.filter(owner=user, pk=budget_id).first()
        if budget:
            return budget
    budget = (
        Budget.objects.filter(owner=user, is_default=True).first()
        or Budget.objects.filter(owner=user).order_by("id").first()
    )
    if budget is None:
        budget = Budget.objects.create(owner=user, name="My Budget", is_default=True)
    return budget


class ActiveBudgetMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.budget = None
        if request.user.is_authenticated:
            request.budget = resolve_active_budget(request)
        return self.get_response(request)
