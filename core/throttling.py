"""The API's anonymous throttle, keyed and stored as the middleware's is."""

from django.core.cache import caches
from rest_framework.throttling import AnonRateThrottle

from core.services.client_ip import get_client_ip


class ClientIPAnonRateThrottle(AnonRateThrottle):
    """DRF's ``AnonRateThrottle``, with two corrections.

    - **The key is the router's address, not the client's header.** With
      ``NUM_PROXIES`` unset, DRF keys on the whole ``X-Forwarded-For`` string,
      which the client writes, so a made-up header was a fresh bucket.
      ``get_ident`` uses ``core.services.client_ip``, as the rate-limit
      middleware does.
    - **The history lives in the per-process ``ratelimit`` cache.** DRF's
      default is the ``default`` alias, which in production is a Postgres
      table, so every anonymous API hit - typeahead search included - was a
      database write. The cost is the middleware's: each gunicorn worker
      counts on its own, so the effective rate is the configured one times
      the worker count.
    """

    @property
    def cache(self):
        # Resolved per access so a test's override_settings(CACHES=...) applies.
        return caches["ratelimit"]

    def get_ident(self, request):
        return get_client_ip(request)
