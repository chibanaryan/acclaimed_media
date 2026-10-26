"""The auth modal's rate limits.

The modal views do allauth's work themselves - ``ResetPasswordForm.save()``,
``EmailAddress.send_confirmation()`` - rather than through allauth's views,
which is where allauth applies its limits. Without these, the forgot-password
and resend-verification buttons mailed an address as fast as they were posted.
"""

from unittest import mock

from allauth.account.models import EmailAddress, EmailConfirmationHMAC
from django.core import mail
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from core.models import User
from core.tests.utils import clear_all_caches
from games.adapters import ModalAccountAdapter

RATE_LIMITED = "you are sending too many requests"


class AuthRateLimitTestBase(TestCase):
    def setUp(self):
        # allauth keeps its counters in the default cache, which the Django
        # runner (unlike pytest's conftest) does not clear between tests.
        clear_all_caches()

    def _user(self, email="reader@example.com", verified=True):
        user = User.objects.create_user(
            username=email, email=email, password="correct-horse-battery"
        )
        EmailAddress.objects.create(
            user=user, email=email, verified=verified, primary=True
        )
        return user


class ForgotPasswordRateLimitTests(AuthRateLimitTestBase):
    @override_settings(ACCOUNT_RATE_LIMITS={"reset_password": "2/m/key"})
    def test_an_address_gets_only_so_many_reset_emails(self):
        self._user()
        url = reverse("auth-modal-forgot-password")

        for _ in range(2):
            response = self.client.post(url, {"email": "reader@example.com"})
            self.assertTemplateUsed(
                response, "auth/partials/_forgot_password_sent.html"
            )

        response = self.client.post(url, {"email": "reader@example.com"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, RATE_LIMITED)
        self.assertEqual(response["HX-Push-Url"], "false")
        self.assertEqual(len(mail.outbox), 2)


class ResendVerificationRateLimitTests(AuthRateLimitTestBase):
    def test_a_second_resend_inside_the_cooldown_sends_nothing(self):
        self._user(verified=False)
        url = reverse("auth-modal-resend-verification")

        self.client.post(url, {"email": "reader@example.com"})
        response = self.client.post(url, {"email": "reader@example.com"})

        # The page still says it was sent; the first email's link still works.
        self.assertTemplateUsed(response, "auth/partials/_verification_resent.html")
        self.assertEqual(len(mail.outbox), 1)


class SignupRateLimitTests(AuthRateLimitTestBase):
    @override_settings(ACCOUNT_RATE_LIMITS={"signup": "1/m/ip"})
    def test_signups_from_one_address_are_limited(self):
        url = reverse("auth-modal-signup")
        data = {
            "password1": "correct-horse-battery",
            "password2": "correct-horse-battery",
        }

        self.client.post(url, dict(data, email="first@example.com"))
        response = self.client.post(url, dict(data, email="second@example.com"))

        self.assertContains(response, RATE_LIMITED)
        self.assertTrue(User.objects.filter(email="first@example.com").exists())
        self.assertFalse(User.objects.filter(email="second@example.com").exists())

    @override_settings(ACCOUNT_RATE_LIMITS={"signup": "1/m/ip"})
    def test_a_limited_signup_keeps_the_typed_username(self):
        url = reverse("auth-modal-signup")
        data = {
            "password1": "correct-horse-battery",
            "password2": "correct-horse-battery",
        }

        self.client.post(url, dict(data, email="first@example.com"))
        response = self.client.post(
            url, dict(data, email="second@example.com", username="chosen_name")
        )

        self.assertContains(response, RATE_LIMITED)
        self.assertContains(response, 'value="chosen_name"')

    def test_the_signup_email_starts_the_resend_cooldown(self):
        url = reverse("auth-modal-signup")
        self.client.post(
            url,
            {
                "email": "new@example.com",
                "password1": "correct-horse-battery",
                "password2": "correct-horse-battery",
            },
        )
        self.client.post(
            reverse("auth-modal-resend-verification"), {"email": "new@example.com"}
        )

        self.assertEqual(len(mail.outbox), 1)


class AdapterClientIPTests(TestCase):
    def test_allauth_keys_on_the_address_the_router_appended(self):
        request = RequestFactory().post("/auth/login/")
        request.META["REMOTE_ADDR"] = "10.1.2.3"  # Heroku's router
        request.META["HTTP_X_FORWARDED_FOR"] = "203.0.113.9, 45.148.10.143"

        self.assertEqual(ModalAccountAdapter().get_client_ip(request), "45.148.10.143")


class EmailConfirmationLoginTests(AuthRateLimitTestBase):
    def test_a_confirmation_that_fails_logs_nobody_in(self):
        user = self._user(verified=False)
        key = EmailConfirmationHMAC(user.emailaddress_set.get()).key

        with mock.patch.object(EmailConfirmationHMAC, "confirm", return_value=None):
            response = self.client.get(
                reverse("account_confirm_email", kwargs={"key": key})
            )

        self.assertFalse(response.context["success"])
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_the_link_logs_in_once(self):
        """allauth's from_key() finds only unverified addresses, so a link
        that leaked after use is not a standing login token."""
        user = self._user(verified=False)
        url = reverse(
            "account_confirm_email",
            kwargs={"key": EmailConfirmationHMAC(user.emailaddress_set.get()).key},
        )

        self.assertTrue(self.client.get(url).context["success"])
        self.client.logout()
        response = self.client.get(url)

        self.assertFalse(response.context["success"])
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_an_unexpected_error_is_logged_not_swallowed(self):
        with mock.patch.object(
            EmailConfirmationHMAC, "from_key", side_effect=RuntimeError("boom")
        ):
            with self.assertLogs("games.views", level="ERROR") as logs:
                response = self.client.get(
                    reverse("account_confirm_email", kwargs={"key": "k"})
                )

        self.assertFalse(response.context["success"])
        self.assertIn("Email confirmation failed", logs.output[0])
