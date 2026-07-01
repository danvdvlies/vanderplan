"""Role-based access decorators for the active budget.

Run these *inside* ``@login_required`` (which is outermost), so the middleware
has already set ``request.can_edit`` / ``request.is_owner``.
"""

from functools import wraps

from django.http import HttpResponseForbidden


def edit_required(view):
    """Block viewers (read-only members) from a mutating view."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not getattr(request, "can_edit", False):
            return HttpResponseForbidden("You have read-only access to this budget.")
        return view(request, *args, **kwargs)

    return wrapped


def owner_required(view):
    """Restrict a view to the owner of the active budget."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not getattr(request, "is_owner", False):
            return HttpResponseForbidden("Only the budget owner can do this.")
        return view(request, *args, **kwargs)

    return wrapped
