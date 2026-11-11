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
        self.assertIn("setTimeout(then, 0);", source)
        self.assertIn("window.addEventListener('load', then, { once: true })", source)
        self.assertIn("whenPageReady(openSignupFromFragment);", source)
        # `#contact` waits the same way, not on a fixed timeout
        self.assertIn("whenPageReady(openContactFromFragment);", source)
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

    def test_a_next_path_is_kept(self):
        """allauth's login page links here with the page the reader came
        from: the modal is on every page, so it opens there."""
        response = self.client.get(
            reverse("account_signup"), {"next": "/game/zelda/?a=1"}
        )
        self.assertEqual(response["Location"], "/game/zelda/?a=1#signup")

    def test_a_next_on_another_site_is_not_followed(self):
        for target in ("https://evil.example/", "//evil.example/", "/accounts/login/"):
            with self.subTest(target=target):
                response = self.client.get(reverse("account_signup"), {"next": target})
                self.assertEqual(response["Location"], "/#signup")

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

    def _waiting_account(self, name, email, *, verified=False):
        user = User.objects.create_user(username=name, email=email, password="pw-12345")
        EmailAddress.objects.create(
            user=user, email=email, verified=verified, primary=True
        )
        return user

    def _log_in(self, name):
        self.client.post(
            reverse("auth-modal-login"), {"login": name, "password": "pw-12345"}
        )

    def test_resending_to_an_address_two_unverified_accounts_share(self):
        """allauth keeps an address unique only once it is verified; `get()`
        on two rows was a 500."""
        self._waiting_account("first", "shared@example.com")
        self._waiting_account("second", "shared@example.com")
        self._log_in("second")
        response = self.client.post(reverse("auth-modal-resend-verification"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Email Sent")

    def test_nothing_is_resent_for_an_address_another_account_has_verified(self):
        """allauth keeps a verified address to one account, so the other's
        row can never be confirmed: a mail for it is a dead link in the
        owner's inbox."""
        from django.core import mail

        self._waiting_account("first", "both@example.com", verified=True)
        self._waiting_account("second", "both@example.com")
        self._log_in("second")
        response = self.client.post(reverse("auth-modal-resend-verification"))
        self.assertContains(response, "Address Already in Use")
        self.assertEqual(mail.outbox, [])

    def test_resending_for_one_of_two_waiting_accounts_mails_once(self):
        from django.core import mail

        self._waiting_account("first", "pair@example.com")
        self._waiting_account("second", "pair@example.com")
        self._log_in("first")
        self.client.post(reverse("auth-modal-resend-verification"))
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


def _confirmation_row(message):
    """The EmailAddress row a verification mail's link confirms."""
    import re

    from allauth.account.models import EmailConfirmationHMAC

    key = re.search(r"/accounts/confirm-email/([^/\s]+)/", message.body).group(1)
    return EmailConfirmationHMAC.from_key(key).email_address


class VerificationBelongsToAnAccountTests(TestCase):
    """A verification is for the account that asked for it, not for whoever
    holds the address or opens the link.

    allauth keeps an address to one account only once it is verified, so
    two accounts can wait on one address. Until 2026-11-11 the resend mailed
    the oldest of them, whichever account the reader had just signed up as,
    and the link logged in whoever opened it: someone who signed up first
    with another person's address and their own password was then signed in
    as an account whose password they knew, by the owner's own click.
    """

    PASSWORD = "a-long-passphrase-1"

    def setUp(self):
        clear_all_caches()
        self.addCleanup(clear_all_caches)

    def _account(self, name, email, *, verified=False):
        user = User.objects.create_user(
            username=name, email=email, password=self.PASSWORD
        )
        EmailAddress.objects.create(
            user=user, email=email, verified=verified, primary=True
        )
        return user

    def _log_in(self, login):
        return self.client.post(
            reverse("auth-modal-login"), {"login": login, "password": self.PASSWORD}
        )

    def test_the_resend_goes_to_the_account_that_logged_in(self):
        from django.core import mail

        self._account("squatter", "shared@example.com")
        owner = self._account("owner", "shared@example.com")
        self.assertContains(self._log_in("owner"), "Email Not Verified")
        self.client.post(reverse("auth-modal-resend-verification"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(_confirmation_row(mail.outbox[0]).user, owner)

    def test_a_posted_address_is_not_whose_link_is_sent(self):
        from django.core import mail

        self._account("waiting", "someone@example.com")
        response = self.client.post(
            reverse("auth-modal-resend-verification"),
            {"email": "someone@example.com"},
        )
        self.assertEqual(mail.outbox, [])
        self.assertContains(response, "Log in")

    def test_signing_up_on_an_address_another_account_waits_on_offers_no_resend(self):
        self._account("squatter", "victim@example.com")
        response = self.client.post(
            reverse("auth-modal-signup"),
            {
                "email": "victim@example.com",
                "password1": self.PASSWORD,
                "password2": self.PASSWORD,
            },
        )
        self.assertNotContains(response, reverse("auth-modal-resend-verification"))
        self.assertContains(response, reverse("auth-modal-forgot-password"))

    def test_the_resend_says_when_another_account_has_verified_the_address(self):
        from django.core import mail

        self._account("owner", "both@example.com", verified=True)
        self._account("latecomer", "both@example.com")
        self._log_in("latecomer")
        response = self.client.post(reverse("auth-modal-resend-verification"))
        self.assertEqual(mail.outbox, [])
        self.assertContains(response, "another account")

    def test_a_resend_for_an_address_already_verified_says_so(self):
        """Verified in another browser, then Resend in the modal left open:
        nothing is sent, and the screen must not say a link is on its way."""
        from django.core import mail

        user = self._account("reader", "done@example.com")
        self._log_in("reader")
        EmailAddress.objects.filter(user=user).update(verified=True)
        response = self.client.post(reverse("auth-modal-resend-verification"))
        self.assertEqual(mail.outbox, [])
        self.assertNotContains(response, "We've sent")
        self.assertContains(response, "Already Verified")

    def test_an_account_with_no_address_row_gets_one_and_a_link(self):
        """Made in the admin, it has no row: its login said unverified, and
        Resend had nothing to confirm."""
        from django.core import mail

        user = User.objects.create_user(
            username="adminmade", email="adminmade@example.com", password=self.PASSWORD
        )
        self.assertContains(self._log_in("adminmade"), "Email Not Verified")
        response = self.client.post(reverse("auth-modal-resend-verification"))
        self.assertContains(response, "Email Sent")
        self.assertEqual(_confirmation_row(mail.outbox[0]).user, user)

    def test_an_account_whose_email_changed_gets_it_as_its_primary(self):
        """Its old row is primary, and a second primary row breaks allauth's
        constraint (a 500); left primary, allauth went on treating the old
        address as the account's. The new one takes over."""
        from django.core import mail

        user = self._account("moved", "old@example.com")
        user.email = "new@example.com"
        user.save()
        self._log_in("moved")
        response = self.client.post(reverse("auth-modal-resend-verification"))
        self.assertContains(response, "Email Sent")
        new = EmailAddress.objects.get(user=user, email="new@example.com")
        self.assertTrue(new.primary)
        self.assertFalse(EmailAddress.objects.get(email="old@example.com").primary)
        self.assertEqual(_confirmation_row(mail.outbox[0]), new)

    def test_a_mixed_case_address_is_stored_lower_case(self):
        """allauth compares lower-cased addresses: a row kept as typed
        escaped its rule that one account holds a verified address."""
        user = User.objects.create_user(
            username="cased", email="Cased@Example.com", password=self.PASSWORD
        )
        self._log_in("cased")
        self.client.post(reverse("auth-modal-resend-verification"))
        self.assertEqual(
            list(
                EmailAddress.objects.filter(user=user).values_list("email", flat=True)
            ),
            ["cased@example.com"],
        )

    def test_pressing_resend_twice_makes_one_row(self):
        user = User.objects.create_user(
            username="twice", email="twice@example.com", password=self.PASSWORD
        )
        self._log_in("twice")
        for _ in range(2):
            response = self.client.post(reverse("auth-modal-resend-verification"))
            self.assertEqual(response.status_code, 200)
        self.assertEqual(EmailAddress.objects.filter(user=user).count(), 1)

    def test_an_account_with_no_email_is_told_so_at_login(self):
        """Not offered a resend that can send nothing."""
        from django.core import mail

        User.objects.create_user(username="noemail", password=self.PASSWORD)
        login = self._log_in("noemail")
        self.assertContains(login, "no email address to verify")
        self.assertNotContains(login, reverse("auth-modal-resend-verification"))
        response = self.client.post(reverse("auth-modal-resend-verification"))
        self.assertEqual(mail.outbox, [])
        self.assertContains(response, "No Address to Verify")
        self.assertContains(response, 'href="/#contact"')

    def test_the_browser_that_signed_up_is_logged_in_by_its_link(self):
        from django.core import mail

        self.client.post(
            reverse("auth-modal-signup"),
            {
                "email": "new@example.com",
                "password1": self.PASSWORD,
                "password2": self.PASSWORD,
            },
        )
        from allauth.account.models import EmailConfirmationHMAC

        row = _confirmation_row(mail.outbox[0])
        key = EmailConfirmationHMAC(row).key
        response = self.client.get(reverse("account_confirm_email", args=[key]))
        self.assertTrue(response.context["success"])
        self.assertEqual(int(self.client.session["_auth_user_id"]), row.user_id)

    def test_a_link_opened_elsewhere_verifies_without_logging_in(self):
        from allauth.account.models import EmailConfirmationHMAC

        user = self._account("reader", "reader@example.com")
        row = EmailAddress.objects.get(user=user)
        response = self.client.get(
            reverse("account_confirm_email", args=[EmailConfirmationHMAC(row).key])
        )
        self.assertTrue(response.context["success"])
        row.refresh_from_db()
        self.assertTrue(row.verified)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(response, "auth-modal-trigger")
