from django.conf import settings

from .models import Budget


def feature_flags(request):
    """Expose simple feature flags to all templates (e.g. the login page)."""
    return {"allow_registration": settings.ALLOW_REGISTRATION}


def budgets(request):
    """Active budget + the user's budget list, for the top-bar switcher."""
    if not request.user.is_authenticated:
        return {}
    return {
        "active_budget": getattr(request, "budget", None),
        "user_budgets": Budget.objects.filter(owner=request.user),
    }
