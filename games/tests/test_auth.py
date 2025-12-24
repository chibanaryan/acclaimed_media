"""
Tests for django-allauth authentication integration.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


User = get_user_model()


class AuthenticationViewsTest(TestCase):
    """Test authentication views."""

    def setUp(self):
        """Create a test user."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )

    def test_login_page_loads(self):
        """Test login page loads successfully."""
        response = self.client.get(reverse("account_login"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "account/login.html")

    def test_signup_page_loads(self):
        """Test signup page loads successfully."""
        response = self.client.get(reverse("account_signup"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "account/signup.html")

    def test_logout_page_loads(self):
        """Test logout page loads when authenticated."""
        self.client.login(username="testuser", password="testpass123")
        response = self.client.get(reverse("account_logout"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "account/logout.html")

    def test_login_with_email(self):
        """Test login with email works."""
        response = self.client.post(
            reverse("account_login"),
            {"login": "test@example.com", "password": "testpass123"},
        )
        self.assertRedirects(response, "/")

    def test_login_with_invalid_credentials(self):
        """Test login with invalid credentials shows error."""
        response = self.client.post(
            reverse("account_login"),
            {"login": "test@example.com", "password": "wrongpassword"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "account/login.html")

    def test_logout_requires_post(self):
        """Test logout requires POST method."""
        self.client.login(username="testuser", password="testpass123")
        # GET shows confirmation page
        response = self.client.get(reverse("account_logout"))
        self.assertEqual(response.status_code, 200)
        # POST actually logs out
        response = self.client.post(reverse("account_logout"))
        self.assertRedirects(response, "/")

    def test_profile_requires_login(self):
        """Test profile page requires authentication."""
        response = self.client.get(reverse("account_profile"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_profile_accessible_when_logged_in(self):
        """Test profile page is accessible when logged in."""
        self.client.login(username="testuser", password="testpass123")
        response = self.client.get(reverse("account_profile"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "account/profile.html")
        self.assertContains(response, "test@example.com")

    def test_password_reset_page_loads(self):
        """Test password reset page loads."""
        response = self.client.get(reverse("account_reset_password"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "account/password_reset.html")

    def test_change_password_requires_login(self):
        """Test change password page requires authentication."""
        response = self.client.get(reverse("account_change_password"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_change_password_accessible_when_logged_in(self):
        """Test change password page is accessible when logged in."""
        self.client.login(username="testuser", password="testpass123")
        response = self.client.get(reverse("account_change_password"))
        self.assertEqual(response.status_code, 200)


class SignupTest(TestCase):
    """Test user registration."""

    def test_signup_creates_user(self):
        """Test successful signup creates a user."""
        self.client.post(
            reverse("account_signup"),
            {
                "email": "newuser@example.com",
                "password1": "ComplexPass123!",
                "password2": "ComplexPass123!",
            },
        )
        self.assertTrue(User.objects.filter(email="newuser@example.com").exists())

    def test_signup_with_mismatched_passwords(self):
        """Test signup fails with mismatched passwords."""
        response = self.client.post(
            reverse("account_signup"),
            {
                "email": "newuser@example.com",
                "password1": "ComplexPass123!",
                "password2": "DifferentPass456!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="newuser@example.com").exists())

    def test_signup_with_existing_email(self):
        """Test signup fails with existing email."""
        User.objects.create_user(
            username="existing",
            email="existing@example.com",
            password="testpass123",
        )
        response = self.client.post(
            reverse("account_signup"),
            {
                "email": "existing@example.com",
                "password1": "ComplexPass123!",
                "password2": "ComplexPass123!",
            },
        )
        self.assertEqual(response.status_code, 200)
        # Should only have the one user we created
        self.assertEqual(User.objects.filter(email="existing@example.com").count(), 1)


class PasswordResetTest(TestCase):
    """Test password reset flow."""

    def setUp(self):
        """Create a test user."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )

    def test_password_reset_page_loads(self):
        """Test password reset page loads."""
        response = self.client.get(reverse("account_reset_password"))
        self.assertEqual(response.status_code, 200)

    def test_password_reset_sends_email(self):
        """Test password reset sends email."""
        from django.core import mail

        self.client.post(
            reverse("account_reset_password"),
            {"email": "test@example.com"},
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("test@example.com", mail.outbox[0].to)


class NavigationAuthLinksTest(TestCase):
    """Test authentication links in navigation."""

    def test_login_link_visible_when_logged_out(self):
        """Test login modal trigger is visible when not authenticated."""
        response = self.client.get(reverse("home"))
        # Login now uses modal trigger instead of direct link
        self.assertContains(response, "auth-modal-trigger")

    def test_profile_link_visible_when_logged_in(self):
        """Test profile dropdown is visible when authenticated."""
        User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )
        self.client.login(username="testuser", password="testpass123")
        response = self.client.get(reverse("home"))
        # Profile now uses modal trigger with dropdown
        self.assertContains(response, "profile-modal-trigger")
        self.assertContains(response, 'href="/accounts/logout/"')


class ToggleSubscriptionTest(TestCase):
    """Test newsletter subscription toggle."""

    def setUp(self):
        """Create a test user."""
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
        )

    def test_toggle_requires_login(self):
        """Test toggle subscription requires authentication."""
        response = self.client.post(reverse("toggle_subscription"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response.url)

    def test_toggle_creates_subscription(self):
        """Test toggle creates subscription for new user."""
        from games.models import Subscriber

        self.client.login(username="testuser", password="testpass123")
        response = self.client.post(reverse("toggle_subscription"))
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertTrue(data["subscribed"])

        # Check subscriber was created
        subscriber = Subscriber.objects.get(email="test@example.com")
        self.assertTrue(subscriber.is_confirmed)
        self.assertTrue(subscriber.is_active)

    def test_toggle_unsubscribes(self):
        """Test toggle unsubscribes existing subscriber."""
        from games.models import Subscriber

        # Create active subscriber
        Subscriber.objects.create(
            email="test@example.com",
            is_confirmed=True,
            is_active=True,
            confirmation_token="test123",
            unsubscribe_token="test456",
        )

        self.client.login(username="testuser", password="testpass123")
        response = self.client.post(reverse("toggle_subscription"))
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertFalse(data["subscribed"])

        # Check subscriber was deactivated
        subscriber = Subscriber.objects.get(email="test@example.com")
        self.assertFalse(subscriber.is_active)

    def test_toggle_resubscribes(self):
        """Test toggle resubscribes inactive subscriber."""
        from games.models import Subscriber

        # Create inactive subscriber
        Subscriber.objects.create(
            email="test@example.com",
            is_confirmed=True,
            is_active=False,
            confirmation_token="test123",
            unsubscribe_token="test456",
        )

        self.client.login(username="testuser", password="testpass123")
        response = self.client.post(reverse("toggle_subscription"))
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertTrue(data["subscribed"])

        # Check subscriber was reactivated
        subscriber = Subscriber.objects.get(email="test@example.com")
        self.assertTrue(subscriber.is_active)
