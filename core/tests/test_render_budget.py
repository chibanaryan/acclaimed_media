"""The per-process budget for renders the page cache cannot answer."""

from django.contrib.auth.models import AnonymousUser
from django.core.cache import caches
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.views.generic import View

from core import sites
from core.mixins import AnonymousResponseCacheMixin
from core.models import User
from core.services import render_budget
from core.tests.utils import clear_all_caches, get_on_site


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class RenderBudgetTests(SimpleTestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.budget = render_budget.RenderBudget(
            per_second=2, burst=3, clock=self.clock
        )

    def test_a_burst_is_allowed_and_no_more(self):
        self.assertEqual([self.budget.spend() for _ in range(4)], [True] * 3 + [False])

    def test_it_refills_at_its_rate(self):
        for _ in range(3):
            self.budget.spend()
        self.clock.now += 0.5  # one render's worth at two a second
        self.assertTrue(self.budget.spend())
        self.assertFalse(self.budget.spend())

    def test_it_never_holds_more_than_its_burst(self):
        self.clock.now += 3600
        self.assertEqual([self.budget.spend() for _ in range(4)], [True] * 3 + [False])


@override_settings(
    ANON_RENDER_BUDGET_ENABLED=True,
    ANON_RENDER_BUDGET_PER_SECOND=1,
    ANON_RENDER_BUDGET_BURST=2,
)
class RefusalTests(SimpleTestCase):
    def setUp(self):
        self.clock = FakeClock()
        render_budget.reset(clock=self.clock)
        self.addCleanup(render_budget.reset)
        self.request = RequestFactory().get("/?series=1")

    def _spend(self, times):
        return [render_budget.refusal(self.request) for _ in range(times)]

    def test_within_the_budget_nothing_is_refused_or_logged(self):
        with self.assertNoLogs("core.services.render_budget"):
            self.assertEqual(self._spend(2), [None, None])

    def test_a_few_past_it_are_not_worth_a_report(self):
        """A crawler on a run of pages, or a reader restoring six tabs: one
        worker sees that every day, and a line each would bury the bursts."""
        with self.assertNoLogs("core.services.render_budget"):
            self.assertEqual(self._spend(2 + 9), [None] * 11)

    def test_ten_past_it_are_noted_and_a_hundred_reported(self):
        """Log-only until a week of it says how often a visitor would be
        refused: turning the refusals on is `ANON_RENDER_BUDGET_ENFORCE`.
        ERROR is what reaches Sentry."""
        with self.assertLogs("core.services.render_budget", "WARNING") as logs:
            self.assertEqual(self._spend(2 + 1234), [None] * 1236)
        self.assertEqual(
            [(record.levelname, record.args[0]) for record in logs.records],
            [("WARNING", 10), ("ERROR", 100), ("ERROR", 1000)],
        )
        self.assertIn("enforcing: False", logs.output[0])
        self.assertIn("/?series=1", logs.output[0])

    def test_a_quiet_spell_ends_the_burst_and_its_count(self):
        with self.assertLogs("core.services.render_budget", "WARNING") as logs:
            self._spend(2 + 15)
            self.clock.now += render_budget.QUIET_AFTER + 1
            # Refilled to its burst of two meanwhile
            self._spend(2 + 10)
        self.assertEqual([record.args[0] for record in logs.records], [10, 10])

    @override_settings(ANON_RENDER_BUDGET_ENFORCE=True)
    def test_enforcing_it_answers_a_plain_429(self):
        response = self._spend(3)[-1]
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response["Content-Type"], "text/plain")
        self.assertEqual(response["Retry-After"], str(render_budget.RETRY_AFTER))
        self.assertEqual(response["Cache-Control"], "no-store")

    @override_settings(ANON_RENDER_BUDGET_ENABLED=False)
    def test_off_it_counts_nothing(self):
        """As under test, where one process makes every request there is."""
        self.assertEqual(self._spend(5), [None] * 5)


class BudgetedPage(AnonymousResponseCacheMixin, View):
    page_cache_timeout = 60

    def get(self, request, *args, **kwargs):
        return HttpResponse("rendered")

    def get_page_cache_key(self):
        if "q" in self.request.GET:
            return None
        return f"budgeted_page:{self.request.GET.get('id', '')}"

    def may_store_page(self):
        return self.request.GET.get("id") != "unknown"


@override_settings(
    ANON_RENDER_BUDGET_ENABLED=True,
    ANON_RENDER_BUDGET_ENFORCE=True,
    ANON_RENDER_BUDGET_PER_SECOND=1,
    ANON_RENDER_BUDGET_BURST=1,
)
class OnlyUncacheableAnonymousPagesSpendTests(TestCase):
    """The budget is for the renders nothing else bounds.

    A page the cache answers costs milliseconds, an HTMX partial follows a
    page that was already let through, and a signed-in reader is not the
    scraper the budget exists for.
    """

    def setUp(self):
        clear_all_caches()
        render_budget.reset(clock=FakeClock())
        self.addCleanup(render_budget.reset)
        self.factory = RequestFactory()

    def _get(self, path="/", user=None, **extra):
        request = self.factory.get(path, **extra)
        request.user = user or AnonymousUser()
        return BudgetedPage.as_view()(request)

    def test_an_uncacheable_anonymous_page_past_the_budget_is_refused(self):
        statuses = [self._get("/?q=x").status_code for _ in range(2)]
        self.assertEqual(statuses, [200, 429])

    def test_a_page_with_a_key_it_will_not_keep_spends_too(self):
        """A page for an id the site does not have is a render every time:
        left out, made-up ids were a way round the budget."""
        statuses = [self._get("/?id=unknown").status_code for _ in range(2)]
        self.assertEqual(statuses, [200, 429])
        self.assertIsNone(caches["local"].get("testserver:budgeted_page:unknown"))

    def test_a_page_the_cache_keeps_never_spends(self):
        self.assertEqual([self._get().status_code for _ in range(4)], [200] * 4)

    def test_an_htmx_request_never_spends(self):
        statuses = [
            self._get("/?q=x", HTTP_HX_REQUEST="true").status_code for _ in range(4)
        ]
        self.assertEqual(statuses, [200] * 4)

    def test_a_head_request_spends_as_the_get_it_is_served_by(self):
        """Django answers HEAD with `get()`. Sent round the cache and the
        budget, it was the whole render, for a body the server drops."""
        statuses = []
        for _ in range(2):
            request = self.factory.head("/?q=x")
            request.user = AnonymousUser()
            statuses.append(BudgetedPage.as_view()(request).status_code)
        self.assertEqual(statuses, [200, 429])

    def test_a_fragment_asked_for_by_its_address_alone_spends(self):
        """`?partial=true` and `?append=true` are the client's to write, and
        took a request round the cache and the budget both. Every script of
        ours sends a header with them, which is what is left uncounted."""
        for query in ("q=x&partial=true", "append=true", "partial=true"):
            with self.subTest(query=query):
                render_budget.reset(clock=FakeClock())
                statuses = [self._get(f"/?{query}").status_code for _ in range(2)]
                self.assertEqual(statuses, [200, 429])
                self.assertIsNone(caches["local"].get("testserver:budgeted_page:"))

    def test_a_fragment_asked_for_with_a_header_never_spends(self):
        for header in (
            {"HTTP_HX_REQUEST": "true"},
            {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"},
        ):
            with self.subTest(header=header):
                statuses = [
                    self._get("/?append=true", **header).status_code for _ in range(4)
                ]
                self.assertEqual(statuses, [200] * 4)

    def test_a_signed_in_reader_never_spends(self):
        user = User.objects.create_user(username="reader", password="pw")
        statuses = [self._get("/?q=x", user=user).status_code for _ in range(4)]
        self.assertEqual(statuses, [200] * 4)

    def test_a_post_never_spends(self):
        for _ in range(4):
            request = self.factory.post("/?q=x")
            request.user = AnonymousUser()
            # The fixture view answers GET alone; the point is that it is asked
            self.assertEqual(BudgetedPage.as_view()(request).status_code, 405)


@override_settings(
    ANON_RENDER_BUDGET_ENABLED=True,
    ANON_RENDER_BUDGET_ENFORCE=True,
    ANON_RENDER_BUDGET_PER_SECOND=1,
    ANON_RENDER_BUDGET_BURST=1,
)
class CsvDownloadsSpendTests(TestCase):
    """The unfiltered file is half a second of rendering in production, and a
    scraper asked for it ~3,900 times a week."""

    def setUp(self):
        clear_all_caches()
        render_budget.reset(clock=FakeClock())
        self.addCleanup(render_budget.reset)

    def _statuses(self, site, viewname, times=2):
        return [
            get_on_site(self.client, site, viewname).status_code for _ in range(times)
        ]

    def test_an_anonymous_download_past_the_budget_is_refused(self):
        for site, viewname in (
            (sites.GAMES, "games-download"),
            (sites.MUSIC, "music:download"),
        ):
            with self.subTest(site=site):
                render_budget.reset(clock=FakeClock())
                self.assertEqual(self._statuses(site, viewname), [200, 429])

    def test_a_signed_in_download_never_spends(self):
        self.client.force_login(User.objects.create_user(username="r", password="pw"))
        for site, viewname in (
            (sites.GAMES, "games-download"),
            (sites.MUSIC, "music:download"),
        ):
            with self.subTest(site=site):
                self.assertEqual(self._statuses(site, viewname, 3), [200] * 3)


@override_settings(
    ANON_RENDER_BUDGET_ENABLED=True,
    ANON_RENDER_BUDGET_ENFORCE=True,
    ANON_RENDER_BUDGET_PER_SECOND=1,
    ANON_RENDER_BUDGET_BURST=1,
)
class RankingsPagesSpendTests(TestCase):
    def setUp(self):
        clear_all_caches()
        render_budget.reset(clock=FakeClock())
        self.addCleanup(render_budget.reset)

    def test_a_made_up_platform_or_genre_id_spends(self):
        for query in ("platforms=987654", "genres=987654"):
            with self.subTest(query=query):
                render_budget.reset(clock=FakeClock())
                statuses = [self.client.get(f"/?{query}").status_code for _ in range(2)]
                self.assertEqual(statuses, [200, 429])

    def test_the_apexs_redirect_of_an_old_filter_link_never_spends(self):
        statuses = [
            get_on_site(
                self.client, sites.ROOT, "landing", query={"genres": "5"}
            ).status_code
            for _ in range(3)
        ]
        self.assertEqual(len(set(statuses)), 1)
        self.assertIn(statuses[0], (301, 302))

    def test_a_tracking_tag_on_a_kept_page_never_spends(self):
        """A link shared on Facebook arrives as `/?fbclid=...` for everyone
        who follows it, and is the page the cache already holds."""
        statuses = [
            self.client.get(f"/?fbclid=visitor{n}&utm_source=x").status_code
            for n in range(4)
        ]
        self.assertEqual(statuses, [200] * 4)
