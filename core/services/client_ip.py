"""The address a request really came from, as Heroku's router saw it."""


def get_client_ip(request):
    """Return the client's IP address: the last ``X-Forwarded-For`` entry.

    Heroku's router *appends* the address it accepted the connection from to
    whatever ``X-Forwarded-For`` the client sent, so only the rightmost entry
    is the router's own word; everything to its left is whatever the client
    chose to write. Reading the leftmost entry, as this used to, let anyone
    take a fresh rate-limit bucket on every request, or put someone else's
    address in the header and get it blocked.

    This holds only while nothing else proxies in front of the router. A CDN
    would append its own edge address after the client's, and the right
    entry would then be one further left.
    """
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        last = forwarded_for.split(",")[-1].strip()
        if last:
            return last
    return request.META.get("REMOTE_ADDR", "unknown")
