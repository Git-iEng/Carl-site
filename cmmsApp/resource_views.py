from pathlib import Path

from django import forms
from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.utils.html import format_html
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .resource_catalog import RESOURCES


class ResourceForm(forms.Form):
    full_name = forms.CharField(
        max_length=120,
        label="Full name",
    )
    email = forms.EmailField(
        label="Email address",
    )
    company = forms.CharField(
        max_length=160,
        label="Company",
    )

    # Hidden field to help reject automated spam submissions.
    website = forms.CharField(
        required=False,
        widget=forms.HiddenInput,
    )

    def clean_website(self):
        if self.cleaned_data.get("website"):
            raise forms.ValidationError("Please try again.")
        return ""


def resources(request):
    return redirect(
        "cmmsApp:resource_download",
        slug="food-plant-benchmark-pack",
    )

@never_cache
@require_http_methods(["GET", "POST"])
def resource_detail(request, slug):
    resource = RESOURCES.get(slug)

    if resource is None:
        raise Http404("Resource not found.")
        # Ask for details again whenever the page is reopened.
    if request.method == "GET":
        request.session.pop("resource_access_" + slug, None)

    form = ResourceForm(
        request.POST if request.method == "POST" else None
    )

    if request.method == "POST" and form.is_valid():
        # Reuse the email helper already used by Contact Us.
        from .views import _send_email

        details = form.cleaned_data

        text_body = (
            "New CARL resource request\n\n"
            f"Resource: {resource['title']}\n"
            f"Name: {details['full_name']}\n"
            f"Email: {details['email']}\n"
            f"Company: {details['company']}\n"
            f"Resource reference: {slug}\n"
        )

        html_body = format_html(
            "<h2>New CARL resource request</h2>"
            "<p><b>Resource:</b> {}</p>"
            "<p><b>Name:</b> {}</p>"
            "<p><b>Email:</b> {}</p>"
            "<p><b>Company:</b> {}</p>"
            "<p><b>Resource reference:</b> {}</p>",
            resource["title"],
            details["full_name"],
            details["email"],
            details["company"],
            slug,
        )

        email_sent = _send_email(
            "New CARL Benchmark Pack / Resource Request",
            text_body,
            str(html_body),
            getattr(settings, "CONTACT_RECIPIENTS", None),
        )

        if email_sent:
            request.session["resource_access_" + slug] = True

            return render(
                request,
                "resource_detail.html",
                {
                    "resource": resource,
                    "slug": slug,
                    "form": form,
                    "unlocked": True,
                },
            )

        form.add_error(
            None,
            "The notification email could not be sent. "
            "Please try again or contact iEngineering.",
        )

    return render(
        request,
        "resource_detail.html",
        {
            "resource": resource,
            "slug": slug,
            "form": form,
            "unlocked": bool(
                request.session.get("resource_access_" + slug)
            ),
        },
    )


@never_cache
@require_http_methods(["GET"])
def resource_download(request, slug):
    resource = RESOURCES.get(slug)

    if resource is None:
        raise Http404("Resource not found.")

    pdf_path = (
        Path(settings.BASE_DIR)
        / "private_resources"
        / resource["filename"]
    )

    if not pdf_path.is_file():
        raise Http404("PDF file not found.")

    response = FileResponse(
        pdf_path.open("rb"),
        as_attachment=False,
        filename=resource["filename"],
        content_type="application/pdf",
    )

    response["X-Content-Type-Options"] = "nosniff"
    return response