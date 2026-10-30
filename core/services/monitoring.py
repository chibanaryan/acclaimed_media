"""Sentry Crons check-ins for the scheduled jobs."""

from contextlib import nullcontext

from sentry_sdk.crons import monitor


def weekly_job_monitor(slug, *, enabled, max_runtime):
    """Check a weekly Heroku Scheduler run in and out of Sentry Crons.

    Heroku Scheduler has no weekly frequency, so both metadata jobs are
    scheduled daily and their ``--weekly`` flag exits at once on any day
    but Sunday. Only a ``--weekly`` run past that gate checks in, against a
    one-week interval: Sentry then alerts on a Sunday that never ran, a run
    that died or overran ``max_runtime`` minutes, or one that raised -
    none of which anything reported before. A manual run (no ``--weekly``)
    does not check in, so it cannot stand in for a missed Sunday. The
    monitor is created in Sentry by the first check-in; with Sentry off
    (locally, under test) the check-ins go nowhere.
    """
    if not enabled:
        return nullcontext()
    return monitor(
        monitor_slug=slug,
        monitor_config={
            "schedule": {"type": "interval", "value": 1, "unit": "week"},
            "checkin_margin": 60,
            "max_runtime": max_runtime,
            "timezone": "UTC",
        },
    )
