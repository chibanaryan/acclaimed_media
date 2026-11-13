"""Helpers shared by the test suites."""

from unittest import mock

from django.conf import settings
from django.core.cache import caches
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from core.cache_helpers import drop_keys, forget_queued_drops


def clear_all_caches():
    """Empty every cache alias, and the drops queued for a commit.

    Tests used to call `cache.clear()`, which only empties `default`. Whole
    rendered pages now live on the per-process `local` alias (see
    `core.cache_config`), so clearing `default` alone lets one test's cached
    page be served to the next one. `conftest.py` does this between tests for
    pytest; this is for the setUp/tearDown calls, which also run under
    Django's own test runner, where there is no conftest.
    """
    for cache in caches.all():
        cache.clear()
    forget_queued_drops()


@override_settings(
    CACHES={
        **settings.CACHES,
        "default": {
            "BACKEND": "django.core.cache.backends.db.DatabaseCache",
            "LOCATION": "cache_table",
        },
    }
)
class DatabaseCacheTestCase(TestCase):
    """A TestCase whose default cache is production's `DatabaseCache`.

    For counting shared-cache round trips (Sentry ACCLAIMED-VIDEO-GAMES-9E),
    which the suite's LocMem default cannot show.
    """

    # What `get_many` sends; a write's SELECTs differ
    CACHE_READ = 'FROM "cache_table" WHERE "cache_key" IN ('

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The test database was built while the default alias was LocMem.
        # Inside the class's transaction, so it is rolled back after it.
        call_command("createcachetable", verbosity=0)

    def cache_reads(self, url):
        """The shared-cache reads one GET of ``url`` makes."""
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        return [
            query["sql"]
            for query in captured.captured_queries
            if self.CACHE_READ in query["sql"]
        ]

    def warm_cache_reads(self, url):
        """`cache_reads` on a second visit, once the first has filled it."""
        self.assertEqual(self.client.get(url).status_code, 200)
        return self.cache_reads(url)


def site_host(site):
    """The public host of ``site`` (core/sites.py), as a test client names it."""
    from urllib.parse import urlsplit

    from django.conf import settings

    return urlsplit(settings.SITE_ORIGINS[site]).netloc


class NoHeartbeatMixin:
    """Keep the metadata lock's heartbeat thread from starting.

    The IGDB and Wikipedia streams and the weekly commands take the lock for
    real. A heartbeat thread that a test leaves behind closes its connection
    whenever it ends, under whatever a later test has patched.
    """

    def setUp(self):
        super().setUp()
        patcher = mock.patch("core.services.post_import._start_heartbeat")
        patcher.start()
        self.addCleanup(patcher.stop)


class CommitHooksRunNowMixin:
    """Run `core.cache_helpers.drop_on_commit` where it is called.

    A ``TestCase`` never commits, so for tests of *what* a signal invalidates
    rather than *when*. The when has tests of its own.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        patcher = mock.patch(
            "core.cache_helpers.drop_on_commit",
            side_effect=lambda *keys, generation_key: drop_keys(
                list(keys), generation_key
            ),
        )
        patcher.start()
        cls.addClassCleanup(patcher.stop)


def get_on_site(client, site, viewname, *, query=None, **kwargs):
    """GET ``viewname`` on ``site``'s own host, over HTTPS.

    For a test that crosses sites: the test client's ``testserver`` host gets
    ``ROOT_URLCONF`` alone, while a site's real host gets that site's
    URLconf, as in production. ``kwargs`` are the URL's.
    """
    from core import sites

    path = sites.site_reverse(site, viewname, kwargs=kwargs or None)
    return client.get(path, query, HTTP_HOST=site_host(site), secure=True)


def select_all(node, selector):
    """``node.select(selector)``, looking inside ``<template>`` elements too.

    soupsieve 4 reads a ``<template>``'s contents as a browser does: not part
    of the document, so a selector finds nothing in one. Alpine's ``x-for``
    and ``x-if`` bodies and the renderers' clone rows are all in templates,
    and a test of that markup asks for it by name, here: with a plain
    ``select`` an ``assertFalse`` over it passes whatever the template holds,
    and a count leaves it out. Matches come back in document order.

    It selects twice: as the document stands, and with every template
    renamed for the moment, which is what lets a selector cross a template's
    edge (``#list .row`` with the list outside and the row inside). The one
    selector neither pass answers names a template and something in it
    (``template > li``): start from the template instead.
    """
    root = node
    while root.parent is not None:
        root = root.parent
    templates = root.find_all("template")
    found = {id(tag): tag for tag in node.select(selector)}
    try:
        for template in templates:
            template.name = "template-seen-into"
        found.update((id(tag), tag) for tag in node.select(selector))
    finally:
        for template in templates:
            template.name = "template"
    return [tag for tag in node.find_all(True) if id(tag) in found]
