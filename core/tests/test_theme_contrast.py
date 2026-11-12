"""The themes' text colours can be read on the themes' backgrounds.

Computed from `theme/static_src/src/styles.css`, so a colour changed there
is checked here. An axe-core run over the main pages on 2026-11-12 found
the dark theme's accent, which is the colour of every link and every row's
rank, at 2.7:1 to 3.6:1 on its backgrounds; its primary, used as a text
colour by a badge and the hover of each platform, at 1.5:1 to 2.0:1; and a
form's label at 4.2:1 on the light theme.
"""

import math
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BASE = Path(settings.BASE_DIR)
STYLES = BASE / "theme/static_src/src/styles.css"
COMPILED = BASE / "theme/static/css/dist/styles.css"
BACKGROUNDS = ("base-100", "base-200", "base-300")
# WCAG 2.1 AA for text that is not large
READABLE = 4.5


def _linear_rgb(lightness, chroma, hue):
    """An OKLCH colour as linear sRGB, clipped to the gamut."""
    a = chroma * math.cos(math.radians(hue))
    b = chroma * math.sin(math.radians(hue))
    long = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    medium = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    short = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return [
        min(max(channel, 0.0), 1.0)
        for channel in (
            4.0767416621 * long - 3.3077115913 * medium + 0.2309699292 * short,
            -1.2684380046 * long + 2.6097574011 * medium - 0.3413193965 * short,
            -0.0041960863 * long - 0.7034186147 * medium + 1.7076147010 * short,
        )
    ]


def _encode(channel):
    """A linear sRGB channel as the display's, where alpha is blended."""
    if channel <= 0.0031308:
        return 12.92 * channel
    return 1.055 * channel ** (1 / 2.4) - 0.055


def _decode(channel):
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def _luminance(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def contrast(text, background):
    lighter, darker = sorted((_luminance(text), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def over(text, background, alpha):
    """``text`` at ``alpha`` over ``background``, blended as a browser does."""
    return [
        _decode(alpha * _encode(fore) + (1 - alpha) * _encode(back))
        for fore, back in zip(text, background)
    ]


def theme_colours(name):
    """A theme's ``--color-*`` values, each as linear sRGB."""
    source = STYLES.read_text(encoding="utf-8")
    block = re.search(
        r'@plugin "daisyui/theme" \{\s*name: "%s";(.*?)\n\}' % name, source, re.S
    ).group(1)
    return {
        key: _linear_rgb(float(lightness) / 100, float(chroma), float(hue))
        for key, lightness, chroma, hue in re.findall(
            r"--color-([\w-]+): oklch\(([\d.]+)% ([\d.]+) ([\d.]+)\);", block
        )
    }


class ThemeContrastTests(SimpleTestCase):
    def test_the_colours_are_read_from_the_stylesheet(self):
        for name in ("lofi", "forest"):
            with self.subTest(theme=name):
                colours = theme_colours(name)
                for key in (*BACKGROUNDS, "base-content", "primary", "accent"):
                    self.assertIn(key, colours)

    def test_the_conversion_agrees_with_a_browser(self):
        """axe-core measured the old accent, #007853, at 3.20:1 on the dark
        theme's base-200 and 3.59:1 on its base-300."""
        forest = theme_colours("forest")
        old_accent = _linear_rgb(0.50, 0.118, 165.612)
        self.assertAlmostEqual(contrast(old_accent, forest["base-200"]), 3.20, 1)
        self.assertAlmostEqual(contrast(old_accent, forest["base-300"]), 3.59, 1)

    def test_the_accent_is_readable_as_text_in_both_themes(self):
        """`link-accent` and `text-accent`: every artist's and developer's
        name, each row's rank, and the links in an article."""
        for name in ("lofi", "forest"):
            colours = theme_colours(name)
            for background in BACKGROUNDS:
                with self.subTest(theme=name, background=background):
                    self.assertGreaterEqual(
                        contrast(colours["accent"], colours[background]), READABLE
                    )

    def test_the_dark_themes_primary_is_never_a_text_colour(self):
        """It is a background colour there, nearly as dark as the page."""
        forest = theme_colours("forest")
        self.assertLess(contrast(forest["primary"], forest["base-100"]), 3)
        source = STYLES.read_text(encoding="utf-8")
        compiled = COMPILED.read_text(encoding="utf-8")
        for selector in (
            '[data-theme="forest"] .text-primary',
            '[data-theme="forest"] .link-primary',
            '[data-theme="forest"] .badge-outline.badge-primary',
            '[data-theme="forest"] .hover\\:text-primary:hover',
            '[data-theme="forest"] .badge-outline.hover\\:badge-primary:hover',
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, source)
                self.assertIn(selector.replace('"', ""), compiled)

    def test_a_form_label_is_readable_in_both_themes(self):
        """DaisyUI's `.label` is the text colour at 60%; ours is at 70%."""
        source = STYLES.read_text(encoding="utf-8")
        alpha = int(
            re.search(
                r"\.label \{\s*color: color-mix\(in oklab, currentcolor (\d+)%",
                source,
            ).group(1)
        )
        for name in ("lofi", "forest"):
            colours = theme_colours(name)
            for background in BACKGROUNDS:
                with self.subTest(theme=name, background=background):
                    shown = over(
                        colours["base-content"], colours[background], alpha / 100
                    )
                    self.assertGreaterEqual(
                        contrast(shown, colours[background]), READABLE
                    )


class VisibleTextIsInTheSpokenNameTests(SimpleTestCase):
    """A control someone drives by voice is named by what it shows ("click
    SNES"): its accessible name has to hold that text (WCAG 2.5.3). The
    platform codes on each row were named "Filter by Super NES", and the
    site menu "Acclaimed Media: switch site" under a label reading "Games"."""

    def test_a_platform_button_is_named_from_its_code_on_both_sides(self):
        row = (
            BASE / "games/templates/games/includes/_game_row_desktop.html"
        ).read_text()
        renderer = (BASE / "games/static/games/js/game-list-renderer.js").read_text()
        self.assertIn(
            'aria-label="{{ p.code }}: filter by {{ p.name }}" '
            'data-add-platforms="{{ p.id }}">{{ p.code }}</button>',
            row,
        )
        self.assertIn(
            'aria-label="${p.code}: filter by ${this._escapeHtml(p.name)}" '
            'data-add-platforms="${p.id}">${p.code}</button>',
            renderer,
        )

    def test_the_site_menu_is_named_for_the_site_it_shows(self):
        menu = (BASE / "core/templates/core/includes/_site_menu.html").read_text()
        self.assertNotIn('aria-label="Acclaimed Media: switch site"', menu)
        self.assertIn("{% else %}Games{% endif %}: switch site", menu)
