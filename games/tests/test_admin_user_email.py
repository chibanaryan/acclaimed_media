"""Changing an account's email in the admin keeps allauth's rows in step.

Until 2026-11-12 the admin wrote ``User.email`` and left the account's
``EmailAddress`` rows as they were. The old row stayed, often primary and
verified, and allauth's password reset reads those rows first: whoever held
the old address could still reset the password. The new address had no row,
so the login said "unverified" and could only point to the contact form.
"""

from allauth.account.forms import ResetPasswordForm
from allauth.account.models import EmailAddress
from django.contrib.messages import get_messages
from django.test import Client, TestCase
from django.urls import reverse

from core.models import User
from core.services.account_email import sync_address_rows


def change_form_data(response):
    """The change page's own form and inlines as the POST a browser sends."""
    data = {}

    def add(form):
        for name, field in form.fields.items():
            if field.disabled:
                continue
            key = form.add_prefix(name)
            value = form[name].value()
            widget = field.widget
            if hasattr(widget, "decompress"):
                for index, part in enumerate(widget.decompress(value)):
                    data[f"{key}_{index}"] = "" if part is None else str(part)
            elif isinstance(value, bool):
                if value:
                    data[key] = "on"
            elif isinstance(value, (list, tuple)):
                data[key] = [str(item) for item in value]
            else:
                data[key] = "" if value is None else str(value)

    add(response.context["adminform"].form)
    for inline in response.context["inline_admin_formsets"]:
        formset = inline.formset
        add(formset.management_form)
        for form in formset.forms:
            add(form)
    return data


class UserAdminEmailChangeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password="pass",
            is_staff=True,
            is_superuser=True,
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.staff)
        self.reader = User.objects.create_user(
            username="reader", email="old@example.com", password="pass"
        )
        self.old_row = EmailAddress.objects.create(
            user=self.reader, email="old@example.com", verified=True, primary=True
        )
        self.url = reverse("admin:core_user_change", args=[self.reader.pk])

    def save(self, **changes):
        data = change_form_data(self.client.get(self.url))
        data.update(changes)
        return self.client.post(self.url, data)

    def rows(self):
        return list(
            EmailAddress.objects.filter(user=self.reader)
            .order_by("email")
            .values_list("email", "verified", "primary")
        )

    def test_the_old_address_can_no_longer_reset_the_password(self):
        response = self.save(email="new@example.com")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.rows(), [("new@example.com", False, True)])
        self.assertFalse(ResetPasswordForm({"email": "old@example.com"}).is_valid())
        self.assertTrue(ResetPasswordForm({"email": "new@example.com"}).is_valid())

    def test_the_new_address_is_stored_lower_case(self):
        """allauth compares lower-case addresses; the admin kept capitals."""
        self.save(email="New@Example.COM")
        self.reader.refresh_from_db()
        self.assertEqual(self.reader.email, "new@example.com")
        self.assertEqual(self.rows(), [("new@example.com", False, True)])

    def test_a_change_of_case_alone_keeps_the_verification(self):
        self.save(email="OLD@example.com")
        self.assertEqual(self.rows(), [("old@example.com", True, True)])

    def test_an_address_another_account_has_verified_is_refused(self):
        other = User.objects.create_user(username="other", email="taken@example.com")
        EmailAddress.objects.create(
            user=other, email="taken@example.com", verified=True, primary=True
        )
        response = self.save(email="Taken@example.com")
        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["adminform"].form.errors)
        self.reader.refresh_from_db()
        self.assertEqual(self.reader.email, "old@example.com")
        self.assertEqual(self.rows(), [("old@example.com", True, True)])

    def test_an_untouched_email_is_not_checked_or_rewritten(self):
        """An abandoned account whose address another has since verified:
        staff could not untick Active, or save anything else, until they
        cleared an email they had not touched."""
        User.objects.filter(pk=self.reader.pk).update(email="Taken@example.com")
        EmailAddress.objects.filter(user=self.reader).delete()
        other = User.objects.create_user(username="other", email="taken@example.com")
        EmailAddress.objects.create(
            user=other, email="taken@example.com", verified=True, primary=True
        )
        response = self.save(first_name="Reader")
        self.assertEqual(response.status_code, 302)
        self.reader.refresh_from_db()
        self.assertEqual(self.reader.first_name, "Reader")
        # As it was: the rows are synced only with a changed email, so the
        # email is not lower-cased without them either
        self.assertEqual(self.reader.email, "Taken@example.com")
        self.assertEqual(self.rows(), [])

    def test_an_address_the_account_had_verified_already_stays_verified(self):
        EmailAddress.objects.create(
            user=self.reader, email="second@example.com", verified=True, primary=False
        )
        self.save(email="second@example.com")
        self.assertEqual(self.rows(), [("second@example.com", True, True)])

    def test_clearing_the_email_leaves_no_rows(self):
        self.save(email="")
        self.assertEqual(self.rows(), [])

    def test_a_save_that_leaves_the_email_alone_leaves_the_rows_alone(self):
        """A secondary address added through allauth is the reader's own."""
        EmailAddress.objects.create(
            user=self.reader, email="second@example.com", verified=False, primary=False
        )
        response = self.save(first_name="Reader")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.rows(),
            [("old@example.com", True, True), ("second@example.com", False, False)],
        )
        self.assertEqual(len(list(get_messages(response.wsgi_request))), 1)

    def test_the_inline_cannot_keep_the_old_row(self):
        """The inline's formset saves after the user; the rows are put right
        after both."""
        data = change_form_data(self.client.get(self.url))
        data["email"] = "new@example.com"
        data.pop("emailaddress_set-0-primary")
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.rows(), [("new@example.com", False, True)])

    def test_staff_are_told_what_happened(self):
        response = self.save(email="new@example.com")
        text = " ".join(str(m) for m in get_messages(response.wsgi_request))
        self.assertIn("old@example.com", text)
        self.assertIn("new@example.com", text)
        self.assertIn("unverified", text)

    def test_no_email_is_sent(self):
        from django.core import mail

        self.save(email="new@example.com")
        self.assertEqual(mail.outbox, [])

    def test_the_reader_can_then_verify_the_new_address(self):
        """With no row for the new address the login could only point to the
        contact form; with one, Resend sends the link."""
        from django.core import mail

        self.save(email="new@example.com")
        reader = Client()
        login = reader.post(
            reverse("auth-modal-login"), {"login": "reader", "password": "pass"}
        )
        self.assertContains(login, "new@example.com")
        self.assertNotContains(login, "contact-modal-trigger")
        reader.post(reverse("auth-modal-resend-verification"))
        self.assertEqual([m.to for m in mail.outbox], [["new@example.com"]])


class SyncAddressRowsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="reader", email="me@example.com")

    def test_two_spellings_of_the_address_become_one_row(self):
        """``unique_together`` compares case, so both rows can exist."""
        EmailAddress.objects.create(user=self.user, email="Me@example.com")
        verified = EmailAddress.objects.create(
            user=self.user, email="ME@example.com", verified=True
        )
        kept, removed = sync_address_rows(self.user)
        self.assertEqual(kept.pk, verified.pk)
        self.assertEqual(
            (kept.email, kept.verified, kept.primary), ("me@example.com", True, True)
        )
        self.assertEqual(removed, [])
        self.assertEqual(EmailAddress.objects.filter(user=self.user).count(), 1)

    def test_an_account_with_no_row_gets_an_unverified_primary_one(self):
        kept, removed = sync_address_rows(self.user)
        self.assertEqual(
            (kept.email, kept.verified, kept.primary), ("me@example.com", False, True)
        )
        self.assertEqual(removed, [])

    def test_the_addresses_removed_are_named(self):
        EmailAddress.objects.create(user=self.user, email="b@example.com", primary=True)
        EmailAddress.objects.create(user=self.user, email="a@example.com")
        kept, removed = sync_address_rows(self.user)
        self.assertEqual(removed, ["a@example.com", "b@example.com"])
        self.assertTrue(kept.primary)
