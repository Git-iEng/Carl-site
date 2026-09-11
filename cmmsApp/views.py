from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.conf import settings
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.core.mail import get_connection, EmailMultiAlternatives
from django.utils import timezone
from django.contrib import messages
from django.core import signing
from django.views.decorators.http import require_POST
from django.contrib.staticfiles.storage import staticfiles_storage
from pathlib import Path
from datetime import datetime
from threading import Thread
import os, re
import secrets, hashlib, hmac, time

from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter
import requests
from django.conf import settings

from .forms import ContactForm
from .utils_excel import append_submission_xlsx
from .utils_contact import normalize_phone_and_country, country_name_from_alpha2
from .utils_security import (
    get_client_ip, is_spam_submission, is_disposable_email,
    generate_form_token, get_ip_debug_info, get_ip_location,
)
from django_ratelimit.decorators import ratelimit


# ---------- Validation patterns ----------
NAME_RE  = re.compile(r"^[A-Za-z\s'.-]{2,}$")
PHONE_RE = re.compile(r"^\+?\d[\d\s\-()]{6,}$")

# ---------- Excel paths ----------
EXCEL_DIR  = os.path.join(settings.BASE_DIR, "data")
EXCEL_PATH = os.path.join(EXCEL_DIR, "carl_demo_requests.xlsx")


# def _append_to_excel(row):
#     """Create/append to the Request Demo workbook."""
#     os.makedirs(EXCEL_DIR, exist_ok=True)
#     if os.path.exists(EXCEL_PATH):
#         wb = load_workbook(EXCEL_PATH)
#         ws = wb.active
#     else:
#         wb = Workbook()
#         ws = wb.active
#         ws.title = "Requests"
#         headers = [
#             "Timestamp", "Full Name", "Company", "Email",
#             "Country", "Dial Code", "Phone", "Address",
#             "Message", "Source IP",
#         ]
#         ws.append(headers)
#         for i in range(1, len(headers) + 1):
#             ws.column_dimensions[get_column_letter(i)].width = 24
#     ws.append(row)
#     wb.save(EXCEL_PATH)


# ---------- Email helpers ----------
def _send_email(subject: str, text_body: str, html_body: str | None, recipients: list[str] | None):
    """Low-level sender. Returns True when SMTP accepts the message."""
    try:
        if not recipients:
            fallback = (
                getattr(settings, "EMAIL_HOST_USER", None)
                or getattr(settings, "DEFAULT_FROM_EMAIL", None)
            )
            recipients = [fallback] if fallback else []

        if not recipients:
            print("EMAIL WARNING: no recipients configured")
            return False

        conn = get_connection(timeout=getattr(settings, "EMAIL_TIMEOUT", 15))
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=(
                getattr(settings, "DEFAULT_FROM_EMAIL", None)
                or getattr(settings, "EMAIL_HOST_USER", None)
            ),
            to=recipients,
            connection=conn,
        )

        if html_body:
            msg.attach_alternative(html_body, "text/html")

        sent_count = msg.send(fail_silently=False)
        print(
            "CONTACT EMAIL RESULT:",
            f"sent_count={sent_count}",
            f"recipients={recipients}",
        )
        return sent_count == 1

    except Exception as e:
        print("EMAIL ERROR:", repr(e))
        return False


def _send_demo_email_async(subject: str, text_body: str, html_body: str | None = None):
    """Fire-and-forget email for Request Demo."""
    recipients = getattr(settings, "DEMO_RECIPIENTS", None) or getattr(settings, "CONTACT_RECIPIENTS", None)
    Thread(target=_send_email, args=(subject, text_body, html_body, recipients), daemon=True).start()


def _send_contact_email_async(subject: str, text_body: str, html_body: str | None = None):
    """Fire-and-forget email for Contact form."""
    recipients = getattr(settings, "CONTACT_RECIPIENTS", None)
    Thread(target=_send_email, args=(subject, text_body, html_body, recipients), daemon=True).start()



# ============================================================
# CHANGE BY JYOTI - 11-Sep-2026
# EMAIL OTP VERIFICATION - START
# ============================================================

CONTACT_OTP_EXPIRY_SECONDS = 3 * 60
CONTACT_OTP_RESEND_SECONDS = 60
CONTACT_OTP_MAX_ATTEMPTS = 5
CONTACT_VERIFICATION_TOKEN_MAX_AGE = 15 * 60

CONTACT_OTP_SESSION_KEY = "contact_email_otp"
CONTACT_VERIFIED_SESSION_KEY = "contact_email_verified"
CONTACT_VERIFICATION_SALT = "contact-email-verification-v1"


def _normalise_email(email: str) -> str:
    return (email or "").strip().lower()


def _hash_contact_otp(email: str, otp: str) -> str:
    message = f"{_normalise_email(email)}:{otp}".encode("utf-8")
    key = settings.SECRET_KEY.encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def _send_contact_otp_email(email: str, otp: str):
    subject = "Your email verification code"
    text_body = (
        "Your email verification code is:\n\n"
        f"{otp}\n\n"
        "This code will expire in 3 minutes.\n\n"
        "If you did not request this code, you can ignore this email."
    )

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=(
            getattr(settings, "DEFAULT_FROM_EMAIL", None)
            or getattr(settings, "EMAIL_HOST_USER", None)
        ),
        to=[email],
    )
    msg.send(fail_silently=False)


def _send_contact_otp_email_async(email: str, otp: str):
    def worker():
        try:
            _send_contact_otp_email(email, otp)
        except Exception as exc:
            print("OTP EMAIL ERROR:", repr(exc))

    Thread(target=worker, daemon=True).start()


@require_POST
def send_email_otp(request):
    email = _normalise_email(request.POST.get("email", ""))

    try:
        validate_email(email)
    except ValidationError:
        return JsonResponse(
            {"ok": False, "message": "Please enter a valid email address."},
            status=400,
        )

    if is_disposable_email(email):
        return JsonResponse(
            {
                "ok": False,
                "message": "Please use a permanent business email address.",
            },
            status=400,
        )

    now = int(time.time())
    current = request.session.get(CONTACT_OTP_SESSION_KEY) or {}
    last_sent_at = int(current.get("sent_at") or 0)

    if (
        current.get("email") == email
        and last_sent_at
        and now - last_sent_at < CONTACT_OTP_RESEND_SECONDS
    ):
        remaining = CONTACT_OTP_RESEND_SECONDS - (now - last_sent_at)

        return JsonResponse(
            {
                "ok": False,
                "message": f"Please wait {remaining} seconds before requesting another OTP.",
                "resend_in": remaining,
            },
            status=429,
        )

    otp = f"{secrets.randbelow(1_000_000):06d}"

    request.session[CONTACT_OTP_SESSION_KEY] = {
        "email": email,
        "otp_hash": _hash_contact_otp(email, otp),
        "sent_at": now,
        "expires_at": now + CONTACT_OTP_EXPIRY_SECONDS,
        "attempts": 0,
    }

    request.session.pop(CONTACT_VERIFIED_SESSION_KEY, None)
    request.session.modified = True

    _send_contact_otp_email_async(email, otp)

    return JsonResponse(
        {
            "ok": True,
            "expires_in": CONTACT_OTP_EXPIRY_SECONDS,
            "resend_in": CONTACT_OTP_RESEND_SECONDS,
        }
    )


@require_POST
def verify_email_otp(request):
    email = _normalise_email(request.POST.get("email", ""))
    otp = (request.POST.get("otp") or "").strip()

    if not re.fullmatch(r"\d{6}", otp):
        return JsonResponse(
            {"ok": False, "message": "Please enter the 6-digit OTP."},
            status=400,
        )

    otp_state = request.session.get(CONTACT_OTP_SESSION_KEY)

    if not otp_state:
        return JsonResponse(
            {"ok": False, "message": "Please request a new OTP."},
            status=400,
        )

    if otp_state.get("email") != email:
        return JsonResponse(
            {
                "ok": False,
                "message": "The email address does not match the OTP request.",
            },
            status=400,
        )

    now = int(time.time())

    if now > int(otp_state.get("expires_at") or 0):
        request.session.pop(CONTACT_OTP_SESSION_KEY, None)
        request.session.modified = True

        return JsonResponse(
            {
                "ok": False,
                "message": "OTP expired. Please request a new OTP.",
            },
            status=400,
        )

    attempts = int(otp_state.get("attempts") or 0)

    if attempts >= CONTACT_OTP_MAX_ATTEMPTS:
        request.session.pop(CONTACT_OTP_SESSION_KEY, None)
        request.session.modified = True

        return JsonResponse(
            {
                "ok": False,
                "message": "Too many incorrect attempts. Please request a new OTP.",
            },
            status=429,
        )

    expected_hash = otp_state.get("otp_hash") or ""
    supplied_hash = _hash_contact_otp(email, otp)

    if not hmac.compare_digest(expected_hash, supplied_hash):
        otp_state["attempts"] = attempts + 1
        request.session[CONTACT_OTP_SESSION_KEY] = otp_state
        request.session.modified = True

        return JsonResponse(
            {"ok": False, "message": "Incorrect OTP."},
            status=400,
        )

    nonce = secrets.token_urlsafe(24)

    request.session[CONTACT_VERIFIED_SESSION_KEY] = {
        "email": email,
        "nonce": nonce,
        "verified_at": now,
    }

    request.session.pop(CONTACT_OTP_SESSION_KEY, None)
    request.session.modified = True

    verification_token = signing.dumps(
        {"email": email, "nonce": nonce},
        salt=CONTACT_VERIFICATION_SALT,
    )

    return JsonResponse(
        {
            "ok": True,
            "verified": True,
            "verification_token": verification_token,
        }
    )


def _is_contact_email_verified(request, email: str, token: str) -> bool:
    email = _normalise_email(email)
    token = (token or "").strip()

    if not email or not token:
        return False

    try:
        payload = signing.loads(
            token,
            salt=CONTACT_VERIFICATION_SALT,
            max_age=CONTACT_VERIFICATION_TOKEN_MAX_AGE,
        )
    except signing.BadSignature:
        return False

    verified_state = request.session.get(CONTACT_VERIFIED_SESSION_KEY) or {}

    return (
        _normalise_email(payload.get("email", "")) == email
        and _normalise_email(verified_state.get("email", "")) == email
        and payload.get("nonce")
        and hmac.compare_digest(
            str(payload.get("nonce")),
            str(verified_state.get("nonce") or ""),
        )
    )


def _consume_contact_email_verification(request):
    request.session.pop(CONTACT_VERIFIED_SESSION_KEY, None)
    request.session.modified = True


# ============================================================
# CHANGE BY JYOTI - 11-Sep-2026
# EMAIL OTP VERIFICATION - END
# ============================================================

# ---------- Views ----------
@ratelimit(key=lambda group, request: get_client_ip(request), rate="5/h", block=True)
def request_demo_view(request):
    if request.method != "POST":
        return redirect("/")

    # CHANGE BY JYOTI - 11-Sep-2026
    # demoform.js submits this form through AJAX.
    wants_json = (
        request.headers.get("x-requested-with") == "XMLHttpRequest"
    )

    # ----------------------------------------------------------
    # Spam diagnostics
    # ----------------------------------------------------------
    # The current Request Demo modal does not include the
    # honeypot/time-trap fields expected by is_spam_submission().
    # Keep the diagnostic log, but do not silently discard a
    # genuine OTP + reCAPTCHA protected enquiry.
    spam, reason = is_spam_submission(request)

    if spam:
        print(
            "REQUEST DEMO SPAM CHECK FLAGGED:",
            f"reason={reason}",
            f"ip={get_client_ip(request)}",
            "- continuing because OTP + reCAPTCHA + rate-limit are active",
        )

    # ----------------------------------------------------------
    # CAPTCHA
    # ----------------------------------------------------------
    if not verify_recaptcha(request):
        message = "Please complete the CAPTCHA."

        if wants_json:
            return JsonResponse(
                {
                    "ok": False,
                    "errors": {
                        "captcha": message,
                    },
                },
                status=400,
            )

        messages.error(request, message)
        return redirect(request.META.get("HTTP_REFERER", "/"))

    # ----------------------------------------------------------
    # Pull fields
    # ----------------------------------------------------------
    full_name = (request.POST.get("full_name") or "").strip()
    company = (request.POST.get("company") or "").strip()

    email = _normalise_email(
        request.POST.get("email", "")
    )

    verification_token = (
        request.POST.get("email_verification_token") or ""
    ).strip()

    phone = (request.POST.get("phone") or "").strip()
    country = (request.POST.get("country") or "").strip()
    address = (request.POST.get("address") or "").strip()
    message = (request.POST.get("message") or "").strip()

    # ----------------------------------------------------------
    # Validation
    # ----------------------------------------------------------
    errors = {}

    if not NAME_RE.match(full_name):
        errors["full_name"] = (
            "Please enter a valid full name (letters only)."
        )

    if not company:
        errors["company"] = "Company is required."

    try:
        validate_email(email)
    except ValidationError:
        errors["email"] = "Enter a valid email."

    if email and is_disposable_email(email):
        errors["email"] = (
            "Please use a permanent business email address."
        )

    if not PHONE_RE.match(phone):
        errors["phone"] = "Enter a valid phone number."

    if not country:
        errors["country"] = "Select a country."

    if errors:
        if wants_json:
            return JsonResponse(
                {
                    "ok": False,
                    "errors": errors,
                },
                status=400,
            )

        for error_message in errors.values():
            messages.error(request, error_message)

        return redirect(request.META.get("HTTP_REFERER", "/"))

    # ----------------------------------------------------------
    # Server-side Email OTP verification
    # ----------------------------------------------------------
    if not _is_contact_email_verified(
        request,
        email,
        verification_token,
    ):
        otp_error = "Please verify your email address."

        if wants_json:
            return JsonResponse(
                {
                    "ok": False,
                    "errors": {
                        "email": otp_error,
                    },
                },
                status=400,
            )

        messages.error(request, otp_error)
        return redirect(request.META.get("HTTP_REFERER", "/"))

    # ----------------------------------------------------------
    # Country value can be "IN|+91"
    # ----------------------------------------------------------
    country_code, dial = (
        country.split("|", 1) + [""]
    )[:2]

    # ----------------------------------------------------------
    # Build notification email
    # ----------------------------------------------------------
    ts = timezone.now().strftime(
        "%Y-%m-%d %H:%M:%S %Z"
    )

    client_ip = get_client_ip(request)
    ip_debug = get_ip_debug_info(request)
    location = get_ip_location(client_ip)

    network_lines = [
        f"Public/WAN IP: {ip_debug['forwarded_ip']}",
    ]

    if location:
        network_lines += [
            f"Country: {location.get('country', 'unknown')}",
            f"Region: {location.get('region', 'unknown')}",
            f"City: {location.get('city', 'unknown')}",
            f"ISP: {location.get('isp', 'unknown')}",
        ]
    else:
        network_lines.append(
            "Location: unavailable "
            "(private/local IP or lookup failed)"
        )

    network_lines.append(
        "Server-seen IP (REMOTE_ADDR): "
        f"{ip_debug['server_seen_ip']}"
    )

    if not ip_debug["proxy_header_present"]:
        network_lines.append(
            "NOTE: no X-Forwarded-For/CF-Connecting-IP "
            "header received — check Nginx proxy config"
        )

    network_block = "\n".join(network_lines)

    subject = "New CARL Software Enquiry"

    text_body = "\n".join(
        [
            "A new CARL Software enquiry was submitted.",
            "",
            f"Submitted: {ts}",
            "",
            "Network Information:",
            network_block,
            "",
            f"Full name: {full_name}",
            f"Company: {company}",
            f"Email: {email}",
            f"Phone: {phone}",
            f"Country: {country_code} {dial}".strip(),
            f"Address: {address}",
            "",
            "Message:",
            message or "(none)",
        ]
    )

    html_network_rows = f"""
        <tr>
            <td><b>Public/WAN IP</b></td>
            <td>{ip_debug['forwarded_ip']}</td>
        </tr>
    """

    if location:
        html_network_rows += f"""
        <tr>
            <td><b>Country</b></td>
            <td>{location.get('country', 'unknown')}</td>
        </tr>
        <tr>
            <td><b>Region</b></td>
            <td>{location.get('region', 'unknown')}</td>
        </tr>
        <tr>
            <td><b>City</b></td>
            <td>{location.get('city', 'unknown')}</td>
        </tr>
        <tr>
            <td><b>ISP</b></td>
            <td>{location.get('isp', 'unknown')}</td>
        </tr>
        """
    else:
        html_network_rows += """
        <tr>
            <td><b>Location</b></td>
            <td>
                unavailable
                (private/local IP or lookup failed)
            </td>
        </tr>
        """

    html_network_rows += f"""
        <tr>
            <td><b>Server-seen IP</b></td>
            <td>{ip_debug['server_seen_ip']}</td>
        </tr>
    """

    html_body = f"""
    <div style="font-family:Arial,Helvetica,sans-serif;max-width:700px;color:#222;">
        <h2 style="margin:0 0 8px;">
            New CARL Software Enquiry
        </h2>

        <p style="margin:0 0 12px;color:#334;">
            Submitted {ts}
        </p>

        <p style="margin:0 0 4px;">
            <b>Network Information</b>
        </p>

        <table
            cellpadding="6"
            cellspacing="0"
            style="border-collapse:collapse;background:#f9fbfc;margin-bottom:12px;"
        >
            {html_network_rows}
        </table>

        <p style="margin:12px 0 4px;">
            <b>Enquiry Information</b>
        </p>

        <table
            cellpadding="6"
            cellspacing="0"
            style="border-collapse:collapse;background:#f9fbfc;"
        >
            <tr><td><b>Full name</b></td><td>{full_name}</td></tr>
            <tr><td><b>Company</b></td><td>{company}</td></tr>
            <tr><td><b>Email</b></td><td>{email}</td></tr>
            <tr><td><b>Phone</b></td><td>{phone}</td></tr>
            <tr><td><b>Country</b></td><td>{country_code} {dial}</td></tr>
            <tr><td><b>Address</b></td><td>{address}</td></tr>
        </table>

        <p style="margin:12px 0 4px;">
            <b>Message</b>
        </p>

        <pre style="white-space:pre-wrap;font-family:Arial,Helvetica,sans-serif;">
{message or '(none)'}
        </pre>
    </div>
    """

    # ----------------------------------------------------------
    # CHANGE BY JYOTI - 11-Sep-2026
    # Send enquiry email synchronously and check SMTP result.
    # ----------------------------------------------------------
    demo_recipients = (
        getattr(settings, "DEMO_RECIPIENTS", None)
        or getattr(settings, "CONTACT_RECIPIENTS", None)
    )

    email_sent = _send_email(
        subject,
        text_body,
        html_body,
        demo_recipients,
    )

    if not email_sent:
        send_error = (
            "Your enquiry was validated, but the notification "
            "email could not be sent. Please try again."
        )

        if wants_json:
            return JsonResponse(
                {
                    "ok": False,
                    "errors": {
                        "email": send_error,
                    },
                },
                status=500,
            )

        messages.error(request, send_error)
        return redirect(request.META.get("HTTP_REFERER", "/"))

    # OTP verification is one-time use after successful submission.
    _consume_contact_email_verification(request)

    messages.success(
        request,
        "Thank you! Your enquiry has been submitted successfully.",
    )

    thanks_url = reverse("cmmsApp:contact_thanks")

    if wants_json:
        return JsonResponse(
            {
                "ok": True,
                "redirect": thanks_url,
            }
        )

    return redirect(thanks_url)


def home(request):
    return render(request, "index.html", {
        "RECAPTCHA_SITE_KEY": settings.RECAPTCHA_SITE_KEY
    })



def sitemap(request):
    with staticfiles_storage.open('sitemap.xml') as sitemap_file:
        return HttpResponse(sitemap_file, content_type='application/xml')
    
    
def request_demo(request):
    return render(request, "request_demo_modal.html", {
        "RECAPTCHA_SITE_KEY": settings.RECAPTCHA_SITE_KEY
    })

def factory(request):     
    return render(request, "factory.html", {
        "RECAPTCHA_SITE_KEY": settings.RECAPTCHA_SITE_KEY
    })


def factory(request):     
    return render(request, "factory.html", {
        "RECAPTCHA_SITE_KEY": settings.RECAPTCHA_SITE_KEY
    })

def healthcare(request):  
    return render(request, "healthcare.html", {
        "RECAPTCHA_SITE_KEY": settings.RECAPTCHA_SITE_KEY
    })


def facility(request):    
    return render(request, "facility.html", {
        "RECAPTCHA_SITE_KEY": settings.RECAPTCHA_SITE_KEY
    })


def city(request):        
    return render(request, "city.html", {
        "RECAPTCHA_SITE_KEY": settings.RECAPTCHA_SITE_KEY
    })


def transport(request):   
    return render(request, "transport.html", {
        "RECAPTCHA_SITE_KEY": settings.RECAPTCHA_SITE_KEY
    })


def contact(request):     
    return render(request, "contact.html", {
        "RECAPTCHA_SITE_KEY": settings.RECAPTCHA_SITE_KEY
    })

def iot(request):         
    return render(request, "iot.html", {
        "RECAPTCHA_SITE_KEY": settings.RECAPTCHA_SITE_KEY
    })

def eam(request):         
    return render(request, "eam.html", {
        "RECAPTCHA_SITE_KEY": settings.RECAPTCHA_SITE_KEY
    })

def apm(request):         
    return render(request, "apm.html", {
        "RECAPTCHA_SITE_KEY": settings.RECAPTCHA_SITE_KEY
    })

def mobility(request):    
    return render(request, "mobility.html", {
        "RECAPTCHA_SITE_KEY": settings.RECAPTCHA_SITE_KEY
    })

def plans(request):       
    return render(request, "plans.html")

def about(request):       
    return render(request, "about.html", {
        "RECAPTCHA_SITE_KEY": settings.RECAPTCHA_SITE_KEY
    })

def workorder(request):   return render(request, "workorder.html")
def compliance(request):  return render(request, "compliance.html")
def cmmsiot(request):       return render(request, "cmms-iot.html")
def gis(request):         return render(request, "gis.html")
def erpsync(request):     return render(request, "erpsync.html")
def industries(request):     return render(request, "industries.html")


@ratelimit(key=lambda group, request: get_client_ip(request), rate="5/h", block=True)
def contact_section(request):
    form = ContactForm(request.POST or None)

    if request.method == "POST":
        # CHANGE BY JYOTI - 11-Sep-2026
        # The current contacts.html does not include the honeypot/time-trap fields
        # expected by utils_security.is_spam_submission(). Keep the diagnostic log,
        # but do not silently discard a genuine contact submission.
        spam, reason = is_spam_submission(request)
        if spam:
            print(
                "CONTACT SPAM CHECK FLAGGED:",
                f"reason={reason}",
                f"ip={get_client_ip(request)}",
                "- continuing because OTP + reCAPTCHA + rate-limit are active",
            )

        if not form.is_valid():
            messages.error(request, "Please correct the highlighted fields and resubmit.")

        elif not verify_recaptcha(request):
            messages.error(request, "Please complete the CAPTCHA.")
            return redirect(request.META.get("HTTP_REFERER", "/"))

        else:
            cd = form.cleaned_data

            email = _normalise_email(cd.get("email", ""))
            verification_token = (
                request.POST.get("email_verification_token") or ""
            ).strip()

            if not _is_contact_email_verified(
                request,
                email,
                verification_token,
            ):
                messages.error(
                    request,
                    "Please verify your email address.",
                )
                return redirect(request.META.get("HTTP_REFERER", "/"))

            e164_phone, resolved_alpha2, resolved_country_name = normalize_phone_and_country(
                cd.get("phone", ""),
                cd.get("country", "")
            )

            # --------------------------------------------------
            # Network / WAN information
            # --------------------------------------------------
            client_ip = get_client_ip(request)
            ip_debug = get_ip_debug_info(request)
            location = get_ip_location(client_ip)

            network_lines = [
                f"Public/WAN IP: {ip_debug['forwarded_ip']}",
            ]

            if location:
                network_lines += [
                    f"Country: {location.get('country', 'unknown')}",
                    f"Region: {location.get('region', 'unknown')}",
                    f"City: {location.get('city', 'unknown')}",
                    f"ISP: {location.get('isp', 'unknown')}",
                ]
            else:
                network_lines.append(
                    "Location: unavailable (private/local IP or lookup failed)"
                )

            network_lines.append(
                f"Server-seen IP (REMOTE_ADDR): {ip_debug['server_seen_ip']}"
            )

            if not ip_debug["proxy_header_present"]:
                network_lines.append(
                    "NOTE: no X-Forwarded-For/CF-Connecting-IP header received "
                    "— check Nginx proxy config"
                )

            network_block = "\n".join(network_lines)

            country_display = (
                resolved_country_name
                or country_name_from_alpha2(resolved_alpha2)
                or cd.get("country", "")
            )

            subject = "New website contact submission for CARL Software"

            # Plain-text email
            text_body = "\n".join(
                [
                    "New contact submission for CARL Software:",
                    "",
                    "Network Information:",
                    network_block,
                    "",
                    f"Name: {cd['first_name']} {cd.get('last_name', '')}".strip(),
                    f"Company: {cd.get('company', '')}",
                    f"Email: {cd['email']}",
                    f"Country: {country_display}",
                    f"Phone: {e164_phone or cd.get('phone', '')}",
                    "",
                    "Message:",
                    cd.get("message", "") or "(none)",
                ]
            )

            # HTML network information
            html_network_rows = f"""
                <tr>
                    <td><b>Public/WAN IP</b></td>
                    <td>{ip_debug['forwarded_ip']}</td>
                </tr>
            """

            if location:
                html_network_rows += f"""
                    <tr>
                        <td><b>Country</b></td>
                        <td>{location.get('country', 'unknown')}</td>
                    </tr>
                    <tr>
                        <td><b>Region</b></td>
                        <td>{location.get('region', 'unknown')}</td>
                    </tr>
                    <tr>
                        <td><b>City</b></td>
                        <td>{location.get('city', 'unknown')}</td>
                    </tr>
                    <tr>
                        <td><b>ISP</b></td>
                        <td>{location.get('isp', 'unknown')}</td>
                    </tr>
                """
            else:
                html_network_rows += """
                    <tr>
                        <td><b>Location</b></td>
                        <td>unavailable (private/local IP or lookup failed)</td>
                    </tr>
                """

            html_network_rows += f"""
                <tr>
                    <td><b>Server-seen IP</b></td>
                    <td>{ip_debug['server_seen_ip']}</td>
                </tr>
            """

           

            html_body = f"""
                <div style="font-family:Arial,Helvetica,sans-serif;max-width:700px;color:#222;">
                    <h2 style="margin:0 0 8px;">New CARL Software Contact Submission</h2>

                    <p style="margin:0 0 4px;"><b>Network Information</b></p>
                    <table cellpadding="6" cellspacing="0"
                           style="border-collapse:collapse;background:#f9fbfc;margin-bottom:12px;">
                        {html_network_rows}
                    </table>

                 

                    <p style="margin:12px 0 4px;"><b>Contact Information</b></p>
                    <table cellpadding="6" cellspacing="0"
                           style="border-collapse:collapse;background:#f9fbfc;">
                        <tr>
                            <td><b>Name</b></td>
                            <td>{cd['first_name']} {cd.get('last_name', '')}</td>
                        </tr>
                        <tr>
                            <td><b>Company</b></td>
                            <td>{cd.get('company', '')}</td>
                        </tr>
                        <tr>
                            <td><b>Email</b></td>
                            <td>{cd['email']}</td>
                        </tr>
                        <tr>
                            <td><b>Country</b></td>
                            <td>{country_display}</td>
                        </tr>
                        <tr>
                            <td><b>Phone</b></td>
                            <td>{e164_phone or cd.get('phone', '')}</td>
                        </tr>
                    </table>

                    <p style="margin:12px 0 4px;"><b>Message</b></p>
                    <pre style="white-space:pre-wrap;font-family:Arial,Helvetica,sans-serif;">
{cd.get('message', '') or '(none)'}
                    </pre>
                </div>
            """

            # CHANGE BY JYOTI - 11-Sep-2026
            # Send synchronously and check the actual SMTP result.
            email_sent = _send_email(
                subject,
                text_body,
                html_body,
                getattr(settings, "CONTACT_RECIPIENTS", None),
            )

            if not email_sent:
                messages.error(
                    request,
                    "Your form was validated, but the notification email could not be sent. "
                    "Please check the server terminal for EMAIL ERROR.",
                )
                return redirect(request.META.get("HTTP_REFERER", "/"))

            _consume_contact_email_verification(request)

            messages.success(
                request,
                "Thank you! Your request has been submitted successfully.",
            )

            return redirect(reverse("cmmsApp:contact_thanks"))

    return render(request, "contact_section.html", {
        "form": form,
        "sent": request.GET.get("sent"),
        "RECAPTCHA_SITE_KEY": settings.RECAPTCHA_SITE_KEY,
    })

def contact_thanks(request):
    return render(request, "contact_thanks.html", {})

def verify_recaptcha(request):
    captcha_response = (request.POST.get("g-recaptcha-response") or "").strip()
    print("captcha_response:", captcha_response)
    print("captcha length:", len(captcha_response) if captcha_response else 0)
    if not captcha_response:
        print("reCAPTCHA failed: no captcha response")
        return False
    data = {
        "secret": settings.RECAPTCHA_SECRET_KEY,
        "response": captcha_response,
    }
    try:
        response = requests.post(
            "https://www.google.com/recaptcha/api/siteverify",
            data=data,
            timeout=10
        )
        result = response.json()
        return result.get("success", False)
    except requests.RequestException as e:
        print("reCAPTCHA request error:", str(e))
        return False
