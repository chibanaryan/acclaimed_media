from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth import get_user_model

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
        """The posted username if it is one, else the email.

        The modal checks a username before it saves, but allauth's own
        forms reach this without it (the social signup page, and its signup
        page until that was closed), so the rules are applied again here:
        a name that breaks them gives way to the email. Until 2026-11-10
        any posted text was taken, another person's email included, which
        then held the name that person's signup defaults to.

        A name some row already holds, verified or not, cannot be taken:
        the column is unique. The modal has freed an abandoned one by now,
        so what is left is a real collision, and allauth generates a name
        from the email, as it would with no adapter. It does the same for an
        email too long for the column.
        """
        User = get_user_model()

        def held(name):
            return User.objects.filter(username__iexact=name).exists()

        posted = request.POST.get("username", "").strip() if request else ""
        email = user.email or ""
        username = email
        if (
            posted
            and posted.lower() != email.lower()
            and User.username_error(posted) is None
            and not held(posted)
        ):
            username = posted
        # The email is the default, and an address can be longer (254
        # characters) than the column holds (150): a DataError on Postgres,
        # until 2026-11-12. One that long gets allauth's generated name too.
        too_long = len(username) > User._meta.get_field("username").max_length
        if too_long or held(username):
            user.username = ""
            return super().populate_username(request, user)
        user.username = username

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
