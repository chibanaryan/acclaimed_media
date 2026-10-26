from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

from core.services.client_ip import get_client_ip


class ModalAccountAdapter(DefaultAccountAdapter):
    """Custom allauth adapter for modal-based authentication.

    Handles email-as-username and modal-friendly redirects.
    """

    def get_client_ip(self, request):
        """The address allauth's per-IP rate limits key on.

        allauth's own default, with ``ALLAUTH_TRUSTED_PROXY_COUNT`` unset, is
        ``REMOTE_ADDR`` - on Heroku the router's, so every visitor shared one
        bucket, and ten failed logins a minute anywhere locked everyone out.
        """
        return get_client_ip(request)

    def populate_username(self, request, user):
        """Set username from form input, or default to email if not provided."""
        custom_username = request.POST.get("username", "").strip() if request else ""
        user.username = custom_username if custom_username else user.email

    def get_login_redirect_url(self, request):
        """Return modal-friendly redirect for HTMX requests."""
        if request.headers.get("HX-Request"):
            return "/"
        return super().get_login_redirect_url(request)

    def get_signup_redirect_url(self, request):
        """Return modal-friendly redirect for HTMX requests."""
        if request.headers.get("HX-Request"):
            return "/"
        return super().get_signup_redirect_url(request)


class ModalSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Custom adapter for social account handling (future use).

    Prepared for future social auth integration (Google, Facebook, etc.).
    """

    pass


# Legacy alias for backwards compatibility
EmailAsUsernameAdapter = ModalAccountAdapter
