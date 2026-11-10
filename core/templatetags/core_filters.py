"""
Shared template filters and tags for the multi-media platform.

These are generic utilities that can be used across games, books,
and future media types.
"""

import json
from datetime import datetime

import markdown as md
from django import template
from django.conf import settings
from django.utils import timezone
from django.utils.safestring import mark_safe

from core import sites

register = template.Library()


@register.simple_tag
def canonical_origin():
    """The apex's public origin, for templates rendered without a request.

    allauth renders its emails with the request when there is one and
    without it otherwise, when the ``canonical_origin`` context processor
    does not run.
    """
    return settings.CANONICAL_ORIGIN


@register.simple_tag(takes_context=True)
def site_url(context, site, viewname, *args, **kwargs):
    """``{% site_url 'music' 'music:home' %}``: an absolute link to another site.

    ``{% url %}`` reverses in the current host's URLconf and gives a path on
    this host; a link to the landing page, games or music from another of
    them needs that site's URLconf and origin (``core.sites.site_url``).
    """
    return sites.site_url(
        site, viewname, *args, request=context.get("request"), **kwargs
    )


@register.filter
def from_now(value):
    """
    Format a datetime as "X ago" similar to moment.js fromNow().
    Only shows the largest unit (e.g., "24 days ago" not "3 weeks, 3 days ago").
    """
    if not value:
        return ""

    try:
        now = timezone.now()

        # Handle string input
        if isinstance(value, str):
            from django.utils.dateparse import parse_datetime

            parsed = parse_datetime(value)
            if parsed:
                value = parsed
            else:
                return ""

        if not isinstance(value, datetime):
            return ""

        delta = now - value

        # If in the future, return "in X"
        if delta.total_seconds() < 0:
            delta = -delta
            prefix = "in "
            suffix = ""
        else:
            prefix = ""
            suffix = " ago"

        total_seconds = delta.total_seconds()

        years = int(total_seconds // (365 * 24 * 60 * 60))
        months = int(total_seconds // (30 * 24 * 60 * 60))
        days = round(total_seconds / (24 * 60 * 60))
        hours = int(total_seconds // (60 * 60))
        minutes = int(total_seconds // 60)

        if years > 0:
            s = "s" if years != 1 else ""
            return f"{prefix}{years} year{s}{suffix}"
        if months > 0:
            s = "s" if months != 1 else ""
            return f"{prefix}{months} month{s}{suffix}"
        if days > 0:
            s = "s" if days != 1 else ""
            return f"{prefix}{days} day{s}{suffix}"
        if hours > 0:
            s = "s" if hours != 1 else ""
            return f"{prefix}{hours} hour{s}{suffix}"
        if minutes > 0:
            s = "s" if minutes != 1 else ""
            return f"{prefix}{minutes} minute{s}{suffix}"
        return "just now"
    except Exception:
        return ""


@register.filter
def tojson(value):
    """Convert a Python value to JSON string, safe for use in JavaScript."""
    return mark_safe(json.dumps(value))


@register.filter
def format_duration(seconds):
    """
    Format duration in seconds to human-readable string.
    Examples: "30s", "2m 30s", "1h 15m"
    """
    if not seconds or seconds < 0:
        return "0s"

    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    if hours > 0:
        if minutes > 0:
            return f"{hours}h {minutes}m"
        return f"{hours}h"
    elif minutes > 0:
        if secs > 0:
            return f"{minutes}m {secs}s"
        return f"{minutes}m"
    else:
        return f"{secs}s"


@register.filter
def markdown(value):
    """Convert markdown text to HTML."""
    if not value:
        return ""
    return mark_safe(md.markdown(value))
