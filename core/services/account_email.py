"""allauth's address rows for an account whose email staff have changed."""

from allauth.account.models import EmailAddress


def sync_address_rows(user):
    """Leave ``user`` the rows a sign-up on its email would have: one.

    Lower-case, primary, and verified only if the account had already
    verified that address. Rows for any other address go: allauth's password
    reset and its login read these rows before ``User.email``, so a row left
    for the old address let whoever held it reset the password. A blank
    email leaves none. Returns the row kept, or None, and the addresses
    removed.

    Deleted before anything is promoted, since an account has one primary
    (``unique_primary_email``). The caller has checked that no other account
    holds the address verified (``unique_verified_email``).
    """
    email = (user.email or "").strip().lower()
    rows = EmailAddress.objects.filter(user=user)
    stale = rows.exclude(email__iexact=email) if email else rows
    removed = sorted(stale.values_list("email", flat=True))
    stale.delete()
    if not email:
        return None, removed

    # `unique_together` compares case, so two spellings can both be here
    same = list(rows.order_by("-verified", "pk"))
    if not same:
        row = EmailAddress.objects.create(
            user=user, email=email, primary=True, verified=False
        )
        return row, removed
    row, extra = same[0], same[1:]
    for other in extra:
        other.delete()
    if row.email != email or not row.primary:
        row.email = email
        row.primary = True
        row.save(update_fields=["email", "primary"])
    return row, removed
