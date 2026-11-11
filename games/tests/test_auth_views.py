"""Tests for authentication adapters and modal-based auth views.

These tests cover the custom allauth adapters (ModalAccountAdapter and
ModalSocialAccountAdapter) and their integration with the modal-based
authentication flow.
"""

from pathlib import Path
from unittest.mock import Mock

from allauth.account.models import EmailAddress
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse

from core.tests.utils import clear_all_caches
from games.adapters import ModalAccountAdapter, ModalSocialAccountAdapter

User = get_user_model()


class ModalAccountAdapterTest(TestCase):
    """Test the ModalAccountAdapter for modal-friendly redirects."""

    def setUp(self):
        self.adapter = ModalAccountAdapter()
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username="testuser@example.com",
            email="testuser@example.com",
            password="testpass123",
        )

    def test_populate_username_uses_email(self):
        """Test that populate_username sets username to email."""
        user = Mock()
        user.email = "newuser@example.com"
        request = self.factory.get("/")

        self.adapter.populate_username(request, user)

        self.assertEqual(user.username, "newuser@example.com")

    def _populated(self, posted, email="newuser@example.com"):
        user = User(email=email)
        request = self.factory.post("/", {"username": posted})
        self.adapter.populate_username(request, user)
        return user.username

    def test_a_posted_username_that_breaks_the_rules_gives_way_to_the_email(self):
        """The modal checks a username before it saves, but the adapter is
        also reached by allauth's own forms, which do not."""
        for posted in ("ab", "x" * 31, "not a name!", "<script>"):
            with self.subTest(posted=posted):
                self.assertEqual(self._populated(posted), "newuser@example.com")

    def test_a_posted_username_within_the_rules_is_kept(self):
        self.assertEqual(self._populated("new_user-1"), "new_user-1")

    def test_another_persons_email_is_not_a_username(self):
        """It would hold the name that person's own signup defaults to."""
        self.assertEqual(self._populated("victim@example.com"), "newuser@example.com")

    def test_a_username_someone_holds_is_not_taken_twice(self):
        """Unverified holders included: the column is unique whoever holds
        it, and a second row was an IntegrityError."""
        User.objects.create_user(username="held", email="held@example.com")
        self.assertEqual(self._populated("held"), "newuser@example.com")

    def test_an_email_someone_holds_as_a_username_gets_a_generated_one(self):
        User.objects.create_user(
            username="newuser@example.com", email="other@example.com"
        )
        username = self._populated("")
        self.assertNotEqual(username, "newuser@example.com")
        self.assertTrue(username)
        self.assertFalse(User.objects.filter(username__iexact=username).exists())

    def test_get_login_redirect_url_htmx_returns_root(self):
        """Test that HTMX login requests redirect to root."""
        request = self.factory.get("/", HTTP_HX_REQUEST="true")
        request.user = self.user

        url = self.adapter.get_login_redirect_url(request)

        self.assertEqual(url, "/")

    def test_get_login_redirect_url_non_htmx_uses_default(self):
        """Test that non-HTMX login requests use default redirect."""
        request = self.factory.get("/")
        request.user = self.user

        url = self.adapter.get_login_redirect_url(request)

        # Default redirect should be something other than necessarily "/"
        # (depends on allauth settings, but shouldn't be forced to "/" for non-HTMX)
        self.assertIsNotNone(url)

    def test_get_signup_redirect_url_htmx_returns_root(self):
        """Test that HTMX signup requests redirect to root."""
        request = self.factory.get("/", HTTP_HX_REQUEST="true")
        request.user = self.user

        url = self.adapter.get_signup_redirect_url(request)

        self.assertEqual(url, "/")

    def test_get_signup_redirect_url_non_htmx_uses_default(self):
        """Test that non-HTMX signup requests use default redirect."""
        request = self.factory.get("/")
        request.user = self.user

        url = self.adapter.get_signup_redirect_url(request)

        # Default redirect should be valid
        self.assertIsNotNone(url)


class ModalSocialAccountAdapterTest(TestCase):
    """Test the ModalSocialAccountAdapter."""

    def test_adapter_instantiates(self):
        """Test that the social adapter can be instantiated."""
        adapter = ModalSocialAccountAdapter()
        self.assertIsNotNone(adapter)

    def test_adapter_inherits_defaults(self):
        """Test that the adapter inherits from DefaultSocialAccountAdapter."""
        from allauth.socialaccount.adapter import DefaultSocialAccountAdapter

        adapter = ModalSocialAccountAdapter()
        self.assertIsInstance(adapter, DefaultSocialAccountAdapter)


class AllauthSignupIsClosedTests(TestCase):
    """Sign-up is the modal's. allauth's own page, still mounted until
    2026-11-10, took any posted username: none of the modal's rules, and a
    name equal to someone's email, which their own signup then collided with.
    """

    def test_a_post_to_allauths_signup_creates_no_account(self):
        response = self.client.post(
            reverse("account_signup"),
            {
                "email": "squatter@example.com",
                "username": "victim@example.com",
                "password1": "a-long-passphrase-1",
                "password2": "a-long-passphrase-1",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/#signup")
        self.assertFalse(User.objects.filter(email="squatter@example.com").exists())

    def test_the_redirect_lands_on_the_modals_sign_up_screen(self):
        """allauth's login page, where a signed-out toggle is sent, links to
        this route: a bare redirect home left that link a dead end."""
        source = (
            Path(settings.BASE_DIR) / "games/static/games/js/modal-handlers.js"
        ).read_text()
        self.assertIn("window.location.hash !== '#signup'", source)
        self.assertIn("openAuthModal(SIGNUP_SCREEN)", source)
        # The script is injected from an idle callback, which can come
        # before htmx has started: it waits for DOMContentLoaded's
        # listeners, or `load` if that event has gone by
        self.assertIn("setTimeout(openSignupFromFragment, 0);", source)
        self.assertIn(
            "window.addEventListener('load', openSignupFromFragment, { once: true })",
            source,
        )
        # Never for a signed-in visitor, whatever link carried it, nor over
        # a screen the visitor opened meanwhile
        self.assertIn("authModal.dataset.signedIn === 'true' || authModal.open", source)
        # A request that fails leaves no open, empty dialog
        self.assertIn("if (authModal.open) authModal.close();", source)
        login = self.client.get(reverse("account_login"))
        self.assertContains(login, reverse("account_signup"))

    def test_the_modal_says_whether_the_visitor_is_signed_in(self):
        """Which is what keeps `/#signup`, followed as a link, from opening
        the sign-up form for someone who has an account open."""
        self.assertContains(self.client.get("/"), 'id="authModal"')
        self.assertContains(self.client.get("/"), 'data-signed-in="false"')
        self.client.force_login(User.objects.create_user(username="reader"))
        self.assertContains(self.client.get("/"), 'data-signed-in="true"')

    def test_a_signed_in_visitor_is_sent_home_with_no_form(self):
        """As allauth's own view sends them away: the modal's sign-up screen
        would let them make a second account while signed in as the first."""
        user = User.objects.create_user(username="reader", password="pw-12345")
        self.client.force_login(user)
        response = self.client.get(reverse("account_signup"))
        self.assertEqual((response.status_code, response["Location"]), (302, "/"))

    def test_the_page_redirects_home(self):
        response = self.client.get(reverse("account_signup"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/#signup")

    def test_signing_up_with_an_email_someone_holds_as_a_username(self):
        """Through the modal: the default username is the email, and a
        verified account already named that was a 500."""
        squatter = User.objects.create_user(
            username="victim@example.com", email="squatter@example.com"
        )
        EmailAddress.objects.create(
            user=squatter, email=squatter.email, verified=True, primary=True
        )
        response = self.client.post(
            reverse("auth-modal-signup"),
            {
                "email": "victim@example.com",
                "password1": "a-long-passphrase-1",
                "password2": "a-long-passphrase-1",
            },
        )
        self.assertEqual(response.status_code, 200)
        created = User.objects.get(email="victim@example.com")
        self.assertNotEqual(created.username, "victim@example.com")


class AuthModalEdgeTests(TestCase):
    def setUp(self):
        # allauth limits confirmation mails per address, in the cache, which
        # only pytest's conftest clears between tests: under Django's runner
        # an earlier test's mail to the same address spent this one's
        clear_all_caches()
        self.addCleanup(clear_all_caches)

    def test_resending_to_an_address_two_unverified_accounts_share(self):
        """allauth keeps an address unique only once it is verified; `get()`
        on two rows was a 500."""
        for name in ("first", "second"):
            user = User.objects.create_user(username=name, email="shared@example.com")
            EmailAddress.objects.create(
                user=user, email="shared@example.com", verified=False, primary=True
            )
        response = self.client.post(
            reverse("auth-modal-resend-verification"), {"email": "shared@example.com"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Email Sent")

    def test_nothing_is_resent_for_an_address_another_account_has_verified(self):
        """allauth keeps a verified address to one account, so the other's
        row can never be confirmed: a mail for it is a dead link in the
        owner's inbox, which anyone could ask for."""
        from django.core import mail

        verified = User.objects.create_user(username="first", email="both@example.com")
        EmailAddress.objects.create(
            user=verified, email="both@example.com", verified=True, primary=True
        )
        waiting = User.objects.create_user(username="second", email="both@example.com")
        EmailAddress.objects.create(
            user=waiting, email="both@example.com", verified=False, primary=True
        )
        response = self.client.post(
            reverse("auth-modal-resend-verification"), {"email": "both@example.com"}
        )
        # The same answer either way: whether the address exists is not said
        self.assertContains(response, "Email Sent")
        self.assertEqual(mail.outbox, [])

    def test_resending_to_two_unverified_accounts_mails_the_oldest_once(self):
        from django.core import mail

        for name in ("first", "second"):
            user = User.objects.create_user(username=name, email="pair@example.com")
            EmailAddress.objects.create(
                user=user, email="pair@example.com", verified=False, primary=True
            )
        self.client.post(
            reverse("auth-modal-resend-verification"), {"email": "pair@example.com"}
        )
        self.assertEqual(len(mail.outbox), 1)

    def test_a_refused_username_does_not_push_the_modals_address(self):
        User.objects.create_user(
            username="profileuser", email="profile@example.com", password="pw-12345"
        )
        self.client.login(username="profileuser", password="pw-12345")
        response = self.client.post(
            reverse("auth-modal-profile"), {"username": "ab"}, HTTP_HX_REQUEST="true"
        )
        self.assertContains(response, "at least 3 characters")
        self.assertEqual(response["HX-Push-Url"], "false")

    def test_changing_only_the_case_of_a_name_keeps_the_account(self):
        """An account made in the admin has no verified address, so freeing
        the name from "abandoned" holders matched the account itself."""
        user = User.objects.create_user(
            username="Casey", email="casey@example.com", password="pw-12345"
        )
        self.client.login(username="Casey", password="pw-12345")
        response = self.client.post(
            reverse("auth-modal-profile"), {"username": "casey"}
        )
        self.assertEqual(response["HX-Refresh"], "true")
        user.refresh_from_db()
        self.assertEqual(user.username, "casey")
