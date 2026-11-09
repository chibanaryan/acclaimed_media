"""A per-process budget for the page renders nothing else bounds.

Twice a day a scraper on a residential-proxy network asked for about 4,000
filtered rankings pages in five minutes, one address each, so the per-address
limit (`games.middleware.RateLimitMiddleware`) never saw it, and each page was
a render: six threads of them, and the site timed out (Sentry uptime,
2026-11-03 to 11-09). The pages it asked for most are now kept whole
(`games.views.rankings.cacheable_facet`). This bounds the rest: an anonymous
page the cache declined, and the CSV downloads.

It is a token bucket per process, not a cache counter: the count is of this
worker's own CPU, and a counter in the shared cache would be a Postgres write
on every render it was meant to save.

**It only reports, by default.** Past the budget it logs as a burst's count
passes 10, at WARNING, and 100, 1,000 and on at ERROR, for Sentry: a handful
of lines that say how big it got, none held back for a worker that may be
recycled first, and none for the few over that a crawler on a run of pages
or a reader restoring their tabs makes every day. An HTMX partial is not
counted: it follows a page that was.
Answering 429 instead is `ANON_RENDER_BUDGET_ENFORCE`: a real visitor to a
page that cannot be kept would be refused during a burst too, so read a week
of the reports before turning it on. Off under test, where one process makes
every request.
"""

import logging
import threading
import time

from django.conf import settings
from django.http import HttpResponse

logger = logging.getLogger(__name__)

# Seconds with nothing over the budget that end a burst and its count, and
# what a refused client is told to wait
QUIET_AFTER = 600
RETRY_AFTER = 10
# The count in one burst from which a report is an ERROR, which Sentry takes
SENTRY_FROM = 100


class RenderBudget:
    """A token bucket: ``burst`` renders at once, ``per_second`` sustained."""

    def __init__(self, per_second, burst, clock=time.monotonic):
        self.per_second = per_second
        self.burst = burst
        self.clock = clock
        self._tokens = float(burst)
        self._filled = clock()
        self._lock = threading.Lock()
        # Renders over the budget in the burst under way, and when the last was
        self._over = 0
        self._last_over = None

    def spend(self):
        """Take one render from the budget. False if there was none to take."""
        with self._lock:
            now = self.clock()
            self._tokens = min(
                self.burst, self._tokens + (now - self._filled) * self.per_second
            )
            self._filled = now
            if self._tokens >= 1:
                self._tokens -= 1
                return True
            return False

    def count_over(self):
        """Count a render over the budget. The burst's count if it is one to
        report - 10, 100, 1,000, ... - else None.

        A burst is thousands of these in five minutes and then nothing for
        hours. Reporting on a timer held most of the count back for the next
        burst, by when the worker had been recycled and had lost it.
        """
        with self._lock:
            now = self.clock()
            if self._last_over is not None and now - self._last_over > QUIET_AFTER:
                self._over = 0
            self._last_over = now
            self._over += 1
            count = self._over
        # A power of ten from ten up: 1 followed by zeros
        return count if count >= 10 and str(count).strip("0") == "1" else None


_budget = None
_budget_lock = threading.Lock()


def reset(clock=time.monotonic):
    """Start the budget afresh, from the settings as they stand."""
    global _budget
    with _budget_lock:
        _budget = RenderBudget(
            settings.ANON_RENDER_BUDGET_PER_SECOND,
            settings.ANON_RENDER_BUDGET_BURST,
            clock=clock,
        )
    return _budget


def refusal(request):
    """Spend one render of the budget on ``request``.

    Returns:
        None, or the 429 to answer with: only past the budget, and only when
        `ANON_RENDER_BUDGET_ENFORCE` is on.
    """
    if not settings.ANON_RENDER_BUDGET_ENABLED:
        return None
    budget = _budget or reset()
    if budget.spend():
        return None
    enforce = settings.ANON_RENDER_BUDGET_ENFORCE
    count = budget.count_over()
    if count is not None:
        logger.log(
            logging.ERROR if count >= SENTRY_FROM else logging.WARNING,
            "Anonymous renders over budget: %d so far in this burst "
            "(enforcing: %s). Latest: %s",
            count,
            enforce,
            request.get_full_path(),
        )
    if not enforce:
        return None
    response = HttpResponse(
        "Too many requests. Try again shortly.",
        status=429,
        content_type="text/plain",
    )
    response["Retry-After"] = str(RETRY_AFTER)
    response["Cache-Control"] = "no-store"
    return response


def anonymous_refusal(request):
    """`refusal`, for a view a signed-in reader may always use."""
    return None if request.user.is_authenticated else refusal(request)
