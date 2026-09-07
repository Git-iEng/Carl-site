"""
utils_security.py
------------------
Shared spam/security helpers for cmmsApp. Import from here in any view
that handles a public form (request_demo_view, contact_section, and any
future subdomain forms sharing this backend).
"""

import ipaddress
import time
from django.core.cache import cache
from django.utils.crypto import get_random_string

MIN_SUBMIT_SECONDS = 3
FORM_TOKEN_TTL_SECONDS = 60 * 30  # 30 minutes

DISPOSABLE_DOMAINS = {
    "mailinator.com", "tempmail.com", "10minutemail.com", "guerrillamail.com",
    "throwawaymail.com", "yopmail.com", "trashmail.com", "fakeinbox.com",
    "getnada.com", "sharklasers.com",
}


def is_public_ip(ip: str) -> bool:
    """
    Returns False for private/reserved ranges (192.168.x.x, 10.x.x.x,
    172.16-31.x.x, 127.x.x.x, link-local, etc.) where geolocation is
    meaningless. Returns True only for real public internet addresses.
    """
    try:
        addr = ipaddress.ip_address(ip)
        return not (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
        )
    except ValueError:
        return False  # empty string, malformed IP, etc.


def get_client_ip(request) -> str:
    """
    Returns the real visitor IP, not the reverse proxy's IP.
    Checks, in order: Cloudflare header, standard X-Forwarded-For chain,
    then falls back to REMOTE_ADDR (direct connection, no proxy).
    """
    cf_ip = request.META.get("HTTP_CF_CONNECTING_IP")
    if cf_ip:
        return cf_ip

    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        # left-most entry in the chain is the original client
        return xff.split(",")[0].strip()

    return request.META.get("REMOTE_ADDR", "")


def get_ip_debug_info(request) -> dict:
    """
    Returns all three IP-related values side by side, so you can tell at a
    glance whether the reverse proxy is forwarding the real client IP.
    - resolved_ip: what get_client_ip() decided is the real visitor IP
    - forwarded_ip: raw X-Forwarded-For / CF-Connecting-IP header, if present
    - server_seen_ip: raw REMOTE_ADDR (the proxy's own connection to Django,
      or the direct connection if there's no proxy)
    If resolved_ip == server_seen_ip and both are private, no proxy header
    is reaching Django — that's the thing to fix in Nginx, not in this code.
    """
    cf_ip = request.META.get("HTTP_CF_CONNECTING_IP", "")
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    server_seen_ip = request.META.get("REMOTE_ADDR", "")
    forwarded_ip = cf_ip or (xff.split(",")[0].strip() if xff else "")

    return {
        "resolved_ip": get_client_ip(request),
        "forwarded_ip": forwarded_ip or "(none received)",
        "server_seen_ip": server_seen_ip,
        "proxy_header_present": bool(forwarded_ip),
    }


def generate_form_token() -> str:
    """
    Call when rendering a page with a public form. Store the token in the
    page context and render it as a hidden input named 'form_token'.
    """
    token = get_random_string(32)
    cache.set(f"formtoken:{token}", time.time(), timeout=FORM_TOKEN_TTL_SECONDS)
    return token


def is_spam_submission(request) -> tuple[bool, str]:
    """
    Runs the honeypot + time-trap checks against a raw POST-based view
    (i.e. one that doesn't use a Django Form class).
    Returns (is_spam: bool, reason: str).
    """
    # Honeypot: real users never fill this hidden field
    if (request.POST.get("website") or "").strip():
        return True, "honeypot"

    # Time-trap: reject submissions faster than a human could plausibly fill the form
    token = request.POST.get("form_token", "")
    rendered_at = cache.get(f"formtoken:{token}")
    if rendered_at is None:
        return True, "missing_or_expired_token"
    if time.time() - rendered_at < MIN_SUBMIT_SECONDS:
        return True, "too_fast"

    cache.delete(f"formtoken:{token}")  # one-time use
    return False, ""


def is_disposable_email(email: str) -> bool:
    domain = email.split("@")[-1].lower() if "@" in email else ""
    return domain in DISPOSABLE_DOMAINS


def get_ip_location(ip: str) -> dict:
    """
    Returns approximate city/region/country for a PUBLIC ip only.
    For private/local IPs (LAN testing, internal proxies), returns an
    empty dict immediately rather than calling the geolocation API with
    a meaningless address.
    """
    if not is_public_ip(ip):
        return {}

    import requests
    try:
        resp = requests.get(f"http://ip-api.com/json/{ip}", timeout=3)
        data = resp.json()
        if data.get("status") == "success":
            return {
                "city": data.get("city"),
                "region": data.get("regionName"),
                "country": data.get("country"),
                "isp": data.get("isp"),
            }
    except requests.RequestException:
        pass
    return {}
