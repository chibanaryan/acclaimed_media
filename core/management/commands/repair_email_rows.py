"""Find and repair accounts whose allauth address rows disagree with their email.

    python manage.py repair_email_rows                  # list them, change nothing
    python manage.py repair_email_rows --sync ada bob   # repair these accounts

allauth's password reset and its login read an account's ``EmailAddress``
rows before ``User.email``. Until 2026-11-12 the admin changed the one and
left the others, so an account whose email staff had changed kept a row,
often primary and verified, for the old address: whoever held that address
could still reset the password. The admin now puts the rows in step as it
saves (``core.services.account_email.sync_address_rows``); this is for the
accounts changed before that.

Not every row for another address is a leftover. A reader can add a second
address of their own at ``/accounts/email/``, and that one is theirs to
keep. So the list says what each row looks like and repairs nothing:
``--sync`` takes the usernames someone has looked at.
"""

from allauth.account.models import EmailAddress
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F

from core.models import User
from core.services.account_email import sync_address_rows


def _row(row):
    marks = [
        mark
        for mark, on in (("primary", row.primary), ("verified", row.verified))
        if on
    ]
    return f"{row.email} ({', '.join(marks) or 'unverified'})"


class Command(BaseCommand):
    help = (
        "List accounts whose allauth address rows disagree with their email, "
        "or repair the ones named with --sync."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--sync",
            nargs="+",
            metavar="USERNAME",
            help=(
                "Leave each of these accounts the one address row a sign-up "
                "on its email would have. Without it nothing is changed."
            ),
        )

    def handle(self, *args, **options):
        if options["sync"]:
            self._sync(options["sync"])
        else:
            self._list()

    def _list(self):
        others = (
            EmailAddress.objects.exclude(email__iexact=F("user__email"))
            .select_related("user")
            .order_by("user__username", "pk")
        )
        by_user = {}
        for row in others:
            by_user.setdefault(row.user, []).append(row)
        if not by_user:
            self.stdout.write("Every address row is for its account's own email.")
            return

        for user, rows in by_user.items():
            own = EmailAddress.objects.filter(user=user, email__iexact=user.email)
            self.stdout.write(f"{user.username}: email {user.email or '(none)'}")
            if not own.exists():
                self.stdout.write("  no row for that email")
            for row in rows:
                # The address allauth's login and reset would use first
                if row.primary or not own.filter(primary=True).exists():
                    kind = "LEFTOVER? it is what a password reset is sent to"
                else:
                    kind = "second address, likely the reader's own"
                self.stdout.write(f"  {_row(row)}: {kind}")
        self.stdout.write(
            f"\n{len(by_user)} account(s). Nothing was changed. To repair: "
            "repair_email_rows --sync <username> ..."
        )

    def _sync(self, usernames):
        failed = []
        for username in usernames:
            user = User.objects.filter(username=username).first()
            if user is None:
                failed.append(f"{username}: no such account")
                continue
            # The one thing sync_address_rows leaves to its caller: a
            # verified address belongs to one account
            taken = (
                EmailAddress.objects.filter(email__iexact=user.email, verified=True)
                .exclude(user=user)
                .exists()
            )
            if user.email and taken:
                failed.append(
                    f"{username}: {user.email} is verified by another account"
                )
                continue
            with transaction.atomic():
                kept, removed = sync_address_rows(user)
            self.stdout.write(
                f"{username}: kept {_row(kept) if kept else 'no address'}; "
                f"removed {', '.join(removed) or 'nothing'}"
            )
        if failed:
            raise CommandError("Not repaired: " + "; ".join(failed))
