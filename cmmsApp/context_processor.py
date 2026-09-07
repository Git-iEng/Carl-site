"""
context_processors.py
----------------------
Injects RECAPTCHA_SITE_KEY and a fresh honeypot/time-trap form_token into
every template render, so the ~15 views that all currently pass
{"RECAPTCHA_SITE_KEY": settings.RECAPTCHA_SITE_KEY} manually don't need to
be touched every time the demo-request modal is included on a new page.
"""

from django.conf import settings
from .utils_security import generate_form_token


def global_form_context(request):
    return {
        "RECAPTCHA_SITE_KEY": getattr(settings, "RECAPTCHA_SITE_KEY", ""),
        "form_token": generate_form_token(),
    }
