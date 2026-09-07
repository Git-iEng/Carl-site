from django.shortcuts import render, redirect
from django.http import HttpResponse
from django.urls import reverse
from django.conf import settings
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.core.mail import get_connection, EmailMultiAlternatives
from django.utils import timezone
from django.contrib import messages
from django.contrib.staticfiles.storage import staticfiles_storage
from pathlib import Path
from datetime import datetime
from threading import Thread
import os, re

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
    """Low-level sender used by async wrappers."""
    try:
        if not recipients:
            # last-resort fallback
            fallback = getattr(settings, "EMAIL_HOST_USER", None) or getattr(settings, "DEFAULT_FROM_EMAIL", None)
            recipients = [fallback] if fallback else []

        if not recipients:
            print("EMAIL WARNING: no recipients configured")
            return

        conn = get_connection(timeout=getattr(settings, "EMAIL_TIMEOUT", 15))
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None) or getattr(settings, "EMAIL_HOST_USER", None),
            to=recipients,
            connection=conn,
        )
        if html_body:
            msg.attach_alternative(html_body, "text/html")
        msg.send(fail_silently=False)
    except Exception as e:
        print("EMAIL ERROR:", repr(e))


def _send_demo_email_async(subject: str, text_body: str, html_body: str | None = None):
    """Fire-and-forget email for Request Demo."""
    recipients = getattr(settings, "DEMO_RECIPIENTS", None) or getattr(settings, "CONTACT_RECIPIENTS", None)
    Thread(target=_send_email, args=(subject, text_body, html_body, recipients), daemon=True).start()


def _send_contact_email_async(subject: str, text_body: str, html_body: str | None = None):
    """Fire-and-forget email for Contact form."""
    recipients = getattr(settings, "CONTACT_RECIPIENTS", None)
    Thread(target=_send_email, args=(subject, text_body, html_body, recipients), daemon=True).start()


# ---------- Views ----------
@ratelimit(key=lambda group, request: get_client_ip(request), rate="5/h", block=True)
def request_demo_view(request):
    if request.method != "POST":
        return redirect("/")

    # Honeypot + time-trap check (silent bot filter, runs before CAPTCHA)
    spam, reason = is_spam_submission(request)
    if spam:
        print(f"SPAM BLOCKED (request_demo): reason={reason} ip={get_client_ip(request)}")
        # Pretend success so bots don't learn which check tripped
        return redirect(reverse("cmmsApp:contact_thanks"))

    # CAPTCHA check
    if not verify_recaptcha(request):
        messages.error(request, "Please complete the CAPTCHA.")
        return redirect(request.META.get("HTTP_REFERER", "/"))

    # Pull fields
    full_name = request.POST.get("full_name", "").strip()
    company   = request.POST.get("company", "").strip()
    email     = request.POST.get("email", "").strip()
    phone     = request.POST.get("phone", "").strip()
    country   = request.POST.get("country", "").strip()  # "IN|+91"
    address   = request.POST.get("address", "").strip()
    message   = request.POST.get("message", "").strip()

    # Validate
    errors = {}
    if not NAME_RE.match(full_name):
        errors["full_name"] = "Please enter a valid full name (letters only)."
    if not company:
        errors["company"] = "Company is required."
    try:
        validate_email(email)
    except ValidationError:
        errors["email"] = "Enter a valid email."
    if email and is_disposable_email(email):
        errors["email"] = "Please use a permanent business email address."
    if not PHONE_RE.match(phone):
        errors["phone"] = "Enter a valid phone number."
    if not country:
        errors["country"] = "Select a country."

    if errors:
        # Raise toasts on next page load
        for msg in errors.values():
            messages.error(request, msg)
        # Go back to the page that opened the modal (so your JS toast can show)
        return redirect(request.META.get("HTTP_REFERER", "/"))

    # Split "IN|+91"
    country_code, dial = (country.split("|", 1) + [""])[:2]

    # Excel append
    # _append_to_excel([
    #     timezone.now().strftime("%Y-%m-%d %H:%M:%S %Z") or timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
    #     full_name, company, email, country_code, dial, phone, address, message,
    #     request.META.get("REMOTE_ADDR", ""),
    # ])

    # Build email
    ts = timezone.now().strftime("%Y-%m-%d %H:%M:%S %Z")
    client_ip = get_client_ip(request)
    ip_debug = get_ip_debug_info(request)
    location = get_ip_location(client_ip)  # {} for private/local IPs

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
        network_lines.append("Location: unavailable (private/local IP or lookup failed)")
    network_lines += [
        f"Server-seen IP (REMOTE_ADDR): {ip_debug['server_seen_ip']}",
    ]
    if not ip_debug["proxy_header_present"]:
        network_lines.append("NOTE: no X-Forwarded-For/CF-Connecting-IP header received — check Nginx proxy config")

    network_block = "\n".join(network_lines)

    subject = "New CARL Demo Request"
    text_body = (
        "A new CARL demo request was submitted.\n\n"
        f"Submitted: {ts}\n\n"
        "Network Information:\n"
        f"{network_block}\n\n"
        f"Full name: {full_name}\n"
        f"Company: {company}\n"
        f"Email: {email}\n"
        f"Phone: {phone}\n"
        f"Country: {country_code} {dial}\n"
        f"Address: {address}\n\n"
        "Message:\n"
        f"{message or '(none)'}\n"
    )
    html_network_rows = f"""
          <tr><td><b>Public/WAN IP</b></td><td>{ip_debug['forwarded_ip']}</td></tr>
    """
    if location:
        html_network_rows += f"""
          <tr><td><b>Country</b></td><td>{location.get('country', 'unknown')}</td></tr>
          <tr><td><b>Region</b></td><td>{location.get('region', 'unknown')}</td></tr>
          <tr><td><b>City</b></td><td>{location.get('city', 'unknown')}</td></tr>
          <tr><td><b>ISP</b></td><td>{location.get('isp', 'unknown')}</td></tr>
        """
    else:
        html_network_rows += """
          <tr><td><b>Location</b></td><td>unavailable (private/local IP or lookup failed)</td></tr>
        """
    html_network_rows += f"""
          <tr><td><b>Server-seen IP</b></td><td>{ip_debug['server_seen_ip']}</td></tr>
    """

    html_body = f"""
        <h2 style="margin:0 0 8px">New CARL Demo Request</h2>
        <p style="margin:0 0 12px;color:#334">Submitted {ts}</p>
        <p style="margin:0 0 4px"><b>Network Information</b></p>
        <table cellpadding="6" cellspacing="0" style="border-collapse:collapse;background:#f9fbfc;margin-bottom:12px">
          {html_network_rows}
        </table>
        <table cellpadding="6" cellspacing="0" style="border-collapse:collapse;background:#f9fbfc">
          <tr><td><b>Full name</b></td><td>{full_name}</td></tr>
          <tr><td><b>Company</b></td><td>{company}</td></tr>
          <tr><td><b>Email</b></td><td>{email}</td></tr>
          <tr><td><b>Phone</b></td><td>{phone}</td></tr>
          <tr><td><b>Country</b></td><td>{country_code} {dial}</td></tr>
          <tr><td><b>Address</b></td><td>{address}</td></tr>
        </table>
        <p style="margin:12px 0 4px"><b>Message</b></p>
        <pre style="white-space:pre-wrap;font-family:system-ui,Segoe UI,Arial,sans-serif">{message or '(none)'}</pre>
    """

    _send_demo_email_async(subject, text_body, html_body)

    # Success -> thanks page
    return redirect(reverse("cmmsApp:contact_thanks"))


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
        spam, reason = is_spam_submission(request)
        if spam:
            print(f"SPAM BLOCKED (contact_section): reason={reason} ip={get_client_ip(request)}")
            # Pretend success so bots don't learn which check tripped
            return redirect(reverse("cmmsApp:contact_thanks"))

        if not form.is_valid():
            messages.error(request, "Please correct the highlighted fields and resubmit.")

        elif not verify_recaptcha(request):
            messages.error(request, "Please complete the CAPTCHA.")
            return redirect(request.META.get("HTTP_REFERER", "/"))

        else:
            cd = form.cleaned_data

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

            _send_contact_email_async(subject, text_body, html_body)
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
