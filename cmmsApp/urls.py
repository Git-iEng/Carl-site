from django.urls import path
from . import views

app_name = "cmmsApp"


urlpatterns = [

    # ============================================================
    # MAIN PAGES
    # ============================================================

    path("", views.home, name="home"),

    path("about/", views.about, name="about"),

    path("factory/", views.factory, name="factory"),

    path("healthcare/", views.healthcare, name="healthcare"),

    path("facility/", views.facility, name="facility"),

    path("city/", views.city, name="city"),

    path("transport/", views.transport, name="transport"),

    path("industries/", views.industries, name="industries"),

    path("iot/", views.iot, name="iot"),

    path("eam/", views.eam, name="eam"),

    path("apm/", views.apm, name="apm"),

    path("mobility/", views.mobility, name="mobility"),

    path("plans/", views.plans, name="plans"),

    path("workorder/", views.workorder, name="workorder"),

    path("compliance/", views.compliance, name="compliance"),

    path("gis/", views.gis, name="gis"),

    path("cmms-iot/", views.cmmsiot, name="cmmsiot"),

    path("erpsync/", views.erpsync, name="erpsync"),


    # ============================================================
    # CONTACT PAGE
    # ============================================================

    path(
        "contacts/",
        views.contact_section,
        name="contact_section",
    ),

    path(
        "contacts/thanks/",
        views.contact_thanks,
        name="contact_thanks",
    ),


    # ============================================================
    # SUBMIT ENQUIRY / REQUEST DEMO
    # ============================================================

    path(
        "request-demo/",
        views.request_demo_view,
        name="request_demo",
    ),


    # ============================================================
    # CHANGE BY JYOTI - 11-Sep-2026
    # EMAIL OTP VERIFICATION
    # ============================================================

    path(
        "api/contact/send-email-otp/",
        views.send_email_otp,
        name="send_email_otp",
    ),

    path(
        "api/contact/verify-email-otp/",
        views.verify_email_otp,
        name="verify_email_otp",
    ),


    # ============================================================
    # SITEMAP
    # ============================================================

    path(
        "sitemap.xml",
        views.sitemap,
        name="sitemap",
    ),
]
