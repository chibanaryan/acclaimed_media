"""Content Security Policy helpers, imported by settings."""

import base64
import hashlib
from urllib.parse import urlparse


def handler_hash(source):
    """The CSP source expression allowing one inline event handler's text."""
    digest = hashlib.sha256(source.encode()).digest()
    return f"'sha256-{base64.b64encode(digest).decode()}'"


def sentry_enabled(dsn, environment, test_mode=False):
    """Whether this process reports to Sentry, CSP reports included.

    Sentry is production's: the local ``.env`` carries the DSN, so every
    runserver, shell and agent script on a laptop filed issues and fired the
    alert emails. Test runs never report. Any environment but "development"
    does, which is how a machine opts in.
    """
    return bool(dsn) and not test_mode and environment.lower() != "development"


def sentry_report_uri(dsn):
    """Sentry's CSP report endpoint for a DSN, or None without one.

    A DSN is ``https://<key>@<host>/<project>``; the endpoint is
    ``https://<host>/api/<project>/security/?sentry_key=<key>``.
    """
    if not dsn:
        return None
    parsed = urlparse(dsn)
    project = parsed.path.strip("/")
    if not (parsed.username and parsed.hostname and project):
        return None
    return (
        f"{parsed.scheme}://{parsed.hostname}/api/{project}/security/"
        f"?sentry_key={parsed.username}"
    )
