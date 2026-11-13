"""`repair_email_rows`: the accounts the admin left with an old address.

ROADMAP asked for the repair "in a command and not `manage.py shell`":
a shell on a dyno reports nothing to Sentry, and there was no command.
"""

from io import StringIO

from allauth.account.models import EmailAddress
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from core.models import User


def run(*args):
    out = StringIO()
    call_command("repair_email_rows", *args, stdout=out)
    return out.getvalue()


class ListingTests(TestCase):
    def test_accounts_in_step_are_not_listed(self):
        user = User.objects.create_user(username="ada", email="ada@example.com")
        EmailAddress.objects.create(
            user=user, email="Ada@Example.com", primary=True, verified=True
        )
        self.assertEqual(run(), "Every address row is for its account's own email.\n")

    def test_an_old_primary_address_is_called_out(self):
        """What the admin left: `User.email` moved on, the row did not."""
        user = User.objects.create_user(username="ada", email="new@example.com")
        EmailAddress.objects.create(
            user=user, email="old@example.com", primary=True, verified=True
        )
        output = run()
        self.assertIn("ada: email new@example.com\n", output)
        self.assertIn("  no row for that email\n", output)
        self.assertIn(
            "  old@example.com (primary, verified): LEFTOVER? it is what a "
            "password reset is sent to\n",
            output,
        )
        self.assertIn("1 account(s). Nothing was changed.", output)
        self.assertEqual(EmailAddress.objects.count(), 1)

    def test_a_second_address_beside_the_accounts_own_is_called_the_readers(self):
        user = User.objects.create_user(username="bob", email="bob@example.com")
        EmailAddress.objects.create(
            user=user, email="bob@example.com", primary=True, verified=True
        )
        EmailAddress.objects.create(
            user=user, email="work@example.com", primary=False, verified=False
        )
        output = run()
        self.assertIn(
            "  work@example.com (unverified): second address, likely the "
            "reader's own\n",
            output,
        )
        self.assertNotIn("no row for that email", output)

    def test_a_stray_row_with_no_primary_anywhere_is_a_leftover(self):
        """With no primary row, allauth takes the first it finds."""
        user = User.objects.create_user(username="cy", email="cy@example.com")
        EmailAddress.objects.create(
            user=user, email="cy@example.com", primary=False, verified=True
        )
        EmailAddress.objects.create(
            user=user, email="old@example.com", primary=False, verified=True
        )
        self.assertIn("old@example.com (verified): LEFTOVER?", run())

    def test_the_listing_costs_the_same_however_many_accounts_it_lists(self):
        for index in range(4):
            user = User.objects.create_user(
                username=f"reader{index}", email=f"new{index}@example.com"
            )
            EmailAddress.objects.create(
                user=user, email=f"new{index}@example.com", primary=True
            )
            EmailAddress.objects.create(
                user=user, email=f"old{index}@example.com", primary=False
            )
        # The rows that disagree, and the listed accounts' own
        with self.assertNumQueries(2):
            output = run()
        self.assertIn("4 account(s).", output)
        self.assertEqual(output.count("second address, likely the reader's own"), 4)

    def test_an_account_with_no_email_is_shown_as_having_none(self):
        user = User.objects.create_user(username="dee", email="")
        EmailAddress.objects.create(
            user=user, email="old@example.com", primary=True, verified=False
        )
        self.assertIn("dee: email (none)\n", run())


class SyncTests(TestCase):
    def test_the_named_account_is_left_one_row_for_its_email(self):
        user = User.objects.create_user(username="ada", email="New@example.com")
        EmailAddress.objects.create(
            user=user, email="old@example.com", primary=True, verified=True
        )
        output = run("--sync", "ada")
        row = EmailAddress.objects.get(user=user)
        self.assertEqual(
            (row.email, row.primary, row.verified), ("new@example.com", True, False)
        )
        self.assertEqual(
            output,
            "ada: kept new@example.com (primary); removed old@example.com\n",
        )

    def test_an_account_not_named_is_left_alone(self):
        ada = User.objects.create_user(username="ada", email="new@example.com")
        bob = User.objects.create_user(username="bob", email="bob@example.com")
        EmailAddress.objects.create(user=ada, email="old@example.com", primary=True)
        EmailAddress.objects.create(user=bob, email="work@example.com", primary=True)
        run("--sync", "ada")
        self.assertEqual(
            list(EmailAddress.objects.filter(user=bob).values_list("email", flat=True)),
            ["work@example.com"],
        )

    def test_an_account_with_no_email_is_left_no_rows(self):
        user = User.objects.create_user(username="dee", email="")
        EmailAddress.objects.create(user=user, email="old@example.com", primary=True)
        self.assertEqual(
            run("--sync", "dee"), "dee: kept no address; removed old@example.com\n"
        )
        self.assertFalse(EmailAddress.objects.filter(user=user).exists())

    def test_an_account_already_in_step_removes_nothing(self):
        user = User.objects.create_user(username="ada", email="ada@example.com")
        EmailAddress.objects.create(
            user=user, email="ada@example.com", primary=True, verified=True
        )
        self.assertEqual(
            run("--sync", "ada"),
            "ada: kept ada@example.com (primary, verified); removed nothing\n",
        )

    def test_an_address_another_account_has_verified_is_refused(self):
        """A verified address belongs to one account; the constraint would
        refuse the write, and a refusal that names the account is kinder."""
        ada = User.objects.create_user(username="ada", email="shared@example.com")
        bob = User.objects.create_user(username="bob", email="shared@example.com")
        EmailAddress.objects.create(
            user=bob, email="shared@example.com", primary=True, verified=True
        )
        EmailAddress.objects.create(user=ada, email="old@example.com", primary=True)
        with self.assertRaisesMessage(
            CommandError, "ada: shared@example.com is verified by another account"
        ):
            run("--sync", "ada")
        self.assertTrue(
            EmailAddress.objects.filter(user=ada, email="old@example.com").exists()
        )

    def test_an_unknown_name_fails_after_the_others_are_repaired(self):
        user = User.objects.create_user(username="ada", email="new@example.com")
        EmailAddress.objects.create(user=user, email="old@example.com", primary=True)
        with self.assertRaisesMessage(CommandError, "nobody: no such account"):
            run("--sync", "nobody", "ada")
        self.assertEqual(
            list(
                EmailAddress.objects.filter(user=user).values_list("email", flat=True)
            ),
            ["new@example.com"],
        )
