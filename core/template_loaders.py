"""Template loaders that drop source indentation once, at compile time.

The games rankings page rendered 1.4 MB of HTML, and 490 KB of it was the
indentation of the template source - every row partial is nested eight or ten
levels deep and is rendered three hundred times. Gzip hid that on the wire,
but every worker still built, deflated into the page cache and buffered the
whole string, inside a 512 MB dyno shared by two of them. See AGENTS.md,
"Production memory budget".

``strip_indentation`` removes leading spaces and tabs from every line and
collapses runs of blank lines into one newline. **Every newline between two
pieces of content survives**, so the page renders identically: in normal-flow
HTML a newline and
a newline plus indentation both collapse to one space. That is why this is not
``django-spaceless-templates`` or ``django-htmlmin``, which remove whitespace
between tags outright and so join ``<a>A</a>\\n<a>B</a>`` into "AB".

Only ``pre``-formatted content would see a difference, so the inside of a
``<pre>`` or ``<textarea>`` element is left as written, as is any template that
is not ``.html`` (email bodies, ``robots.txt``, the sitemap). No template uses
``white-space: pre`` in CSS - keep it that way, or exempt that element here.

Lines holding only a ``{% if %}`` or ``{% for %}`` still render as empty lines.
Trimming them is worth ~15 KB on the rankings page, and doing it safely would
mean knowing which tags print nothing, so it is not attempted.

The loaders are the inner loaders of the cached loader in production, so the
stripping costs nothing per request.
"""

import re

from django.template.loaders import app_directories, filesystem

# After a newline rather than at ``^``, so the whitespace following a closing
# ``</pre>`` on the same line - which does render - is kept.
_LEADING_WHITESPACE = re.compile(r"(?<=\n)[ \t]+")
_BLANK_LINES = re.compile(r"\n\s*\n")
_PREFORMATTED = re.compile(r"(<(pre|textarea)\b.*?</\2\s*>)", re.IGNORECASE | re.DOTALL)


def _strip(text):
    return _BLANK_LINES.sub("\n", _LEADING_WHITESPACE.sub("", text))


def strip_indentation(source):
    """Return ``source`` without indentation or blank lines, outside
    ``<pre>`` and ``<textarea>`` elements."""
    parts = _PREFORMATTED.split(source)
    # split() yields text, element, tag name, text, element, tag name, ...
    return "".join(
        _strip(part) if i % 3 == 0 else part
        for i, part in enumerate(parts)
        if i % 3 != 2
    )


class _StripIndentationMixin:
    def get_contents(self, origin):
        source = super().get_contents(origin)
        if origin.template_name.endswith(".html"):
            return strip_indentation(source)
        return source


class FilesystemLoader(_StripIndentationMixin, filesystem.Loader):
    pass


class AppDirectoriesLoader(_StripIndentationMixin, app_directories.Loader):
    pass
