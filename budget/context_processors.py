from django.conf import settings


def feature_flags(request):
    """Expose simple feature flags to all templates (e.g. the login page)."""
    return {"allow_registration": settings.ALLOW_REGISTRATION}
