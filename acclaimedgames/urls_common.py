"""
The routes every site serves, and the debug and static routes around them.

Each site has its own URLconf (``settings.SITE_URLCONFS``, chosen by host in
``core.middleware.SiteHostMiddleware``): ``urls_root`` for the landing page,
``urls_games`` and ``urls_music``. Sign-in, the contact form, the shared
pages and the admin are the same on all three, so a visitor never leaves the
site they are on to use them. The session cookie spans the subdomains, so
signing in on one signs in on all.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

from core import views as core_views
from games import views


def common_urlpatterns(sitemaps):
    """The shared routes, with ``sitemaps`` as this site's ``sitemap.xml``."""
    return [
        path(
            "sitemap.xml",
            sitemap,
            {"sitemaps": sitemaps},
            name="django.contrib.sitemaps.views.sitemap",
        ),
        path("robots.txt", views.robots_txt, name="robots-txt"),
        path("healthz/", core_views.healthz, name="healthz"),
        path("admin/", admin.site.urls),
        # Custom email confirmation page (must be before allauth include)
        path(
            "accounts/confirm-email/<str:key>/",
            views.EmailConfirmationView.as_view(),
            name="account_confirm_email",
        ),
        path("accounts/", include("allauth.urls")),
        # Auth modal partials (HTMX)
        path(
            "auth/modal/login/",
            views.AuthModalLoginView.as_view(),
            name="auth-modal-login",
        ),
        path(
            "auth/modal/signup/",
            views.AuthModalSignupView.as_view(),
            name="auth-modal-signup",
        ),
        path(
            "auth/modal/profile/",
            views.AuthModalProfileView.as_view(),
            name="auth-modal-profile",
        ),
        path(
            "auth/modal/forgot-password/",
            views.AuthModalForgotPasswordView.as_view(),
            name="auth-modal-forgot-password",
        ),
        path(
            "auth/modal/resend-verification/",
            views.AuthModalResendVerificationView.as_view(),
            name="auth-modal-resend-verification",
        ),
        path(
            "auth/logout/",
            views.AuthLogoutView.as_view(),
            name="auth-logout",
        ),
        path("contact/", views.ContactFormView.as_view(), name="contact"),
        path(
            "contact/thank-you/",
            views.ContactThankYouView.as_view(),
            name="contact_thank_you",
        ),
        # Newsletter unsubscribe (for links in notification emails)
        path(
            "unsubscribe/<str:token>/",
            views.UnsubscribeView.as_view(),
            name="unsubscribe",
        ),
        # About, Donate, Privacy, Legal: one copy, shared by every site
        path("page/<slug:slug>/", views.PageDetailView.as_view(), name="page-detail"),
    ]


def with_debug_and_static(urlpatterns):
    """``urlpatterns`` with the static routes, and in DEBUG the dev tools."""
    if not settings.DEBUG:
        return urlpatterns + static(
            settings.STATIC_URL, document_root=settings.STATIC_ROOT
        )

    from django.views.defaults import page_not_found

    if settings.DEBUG_TOOLBAR:
        import debug_toolbar

        urlpatterns = [path("__debug__/", include(debug_toolbar.urls)), *urlpatterns]

    return [
        # Test route to preview custom 404 page
        path(
            "test-404/",
            lambda request: page_not_found(request, Exception("Test 404")),
        ),
        *urlpatterns,
    ] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
