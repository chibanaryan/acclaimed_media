"""Sentry event processing, imported by settings."""

from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber

# Field names the default denylist misses, which it matches whole: allauth's
# sign-up and password-change forms post their passwords under these.
EXTRA_DENYLIST = [
    "password1",
    "password2",
    "oldpassword",
    "new_password1",
    "new_password2",
    "unsubscribe_token",
]


def event_scrubber():
    """The default scrubber, with the field names our forms use."""
    return EventScrubber(denylist=DEFAULT_DENYLIST + EXTRA_DENYLIST)


def name_unrouted_transactions(event, hint):
    """Give the requests that matched no route a few names, not one each.

    A ``before_send_transaction`` hook. Sentry's Django integration names a
    transaction after the route it matched (``/game/{slug}/``), and one that
    matched none after its raw path. So each scanner probe and each
    slash-less link was a transaction of its own (``/config.env``,
    ``/wp-admin/install.php``, ``/developers/valve``), thousands a week, and
    the list of transactions was mostly those. They are named for how they
    were answered instead: ``unrouted 404``, ``redirect 301``.

    Only a 404 and a redirect. A path answered some other way with no route
    matched is a real page or file - WhiteNoise's ``/static/...``, a flat
    page from its fallback middleware - and keeps its name. A redirect is
    not called unrouted: ``SecurityMiddleware`` sends http to https before
    the site's URLconf is chosen, for paths that have a route.
    """
    info = event.get("transaction_info") or {}
    if info.get("source") != "url":
        return event
    response = (event.get("contexts") or {}).get("response") or {}
    status = response.get("status_code")
    if status == 404:
        name = "unrouted 404"
    elif status in (301, 302, 307, 308):
        name = f"redirect {status}"
    else:
        return event
    event["transaction"] = name
    # No longer a URL, which Sentry would go on trying to group by its parts
    event["transaction_info"] = {**info, "source": "custom"}
    return event
