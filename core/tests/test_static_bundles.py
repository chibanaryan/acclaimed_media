"""Tests for the client-side filtering bundles.

Two failures shipped in the books bundle and went unnoticed because nothing
tested either: the template referenced a filename the build script does not
write, and the bundle omitted the base class its renderer extends - which
throws a ReferenceError as the bundle loads, so nothing declared after that
point registers either. Both are checked here for every app at once, because
both are mistakes a reader cannot see.
"""

import re
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import SimpleTestCase

TEMPLATE_DIRS = ["games", "books", "music", "core"]

# `{% static 'app/js/x.bundle.min.js' %}`, either quote style.
BUNDLE_REFERENCE = re.compile(
    r"""{%\s*static\s*['"]([^'"]+\.bundle\.min\.js)['"]\s*%}"""
)
CLASS_DECLARATION = re.compile(r"class\s+(\w+)(?:\s+extends\s+(\w+))?")


def _referenced_bundles():
    """Every bundle path referenced from a template, with its template."""
    found = []
    for app in TEMPLATE_DIRS:
        root = Path(settings.BASE_DIR) / app / "templates"
        if not root.exists():
            continue
        for template in root.rglob("*.html"):
            for match in BUNDLE_REFERENCE.finditer(template.read_text()):
                found.append((template, match.group(1)))
    return found


class ReferencedBundlesExistTests(SimpleTestCase):
    """A bundle a template asks for has to be a file that exists.

    Under production's manifest static storage, a `{% static %}` name missing
    from the manifest raises while rendering rather than 404ing, so a typo
    here takes the page down rather than degrading it.
    """

    def test_some_bundles_are_referenced(self):
        # Guards the regex: an empty sweep would make the test below vacuous.
        self.assertTrue(_referenced_bundles())

    def test_every_referenced_bundle_is_findable(self):
        for template, path in _referenced_bundles():
            with self.subTest(template=template.name, path=path):
                self.assertIsNotNone(
                    finders.find(path),
                    f"{template} references {path}, which no app serves. "
                    f"The name must match the bundle scripts/minify_js.sh "
                    f"writes.",
                )


class BundleContentsTests(SimpleTestCase):
    """A bundle must carry the base classes its own members extend."""

    def test_base_classes_are_declared_before_their_subclasses(self):
        bundles = {path for _, path in _referenced_bundles()}
        self.assertTrue(bundles)

        for path in sorted(bundles):
            with self.subTest(bundle=path):
                source = Path(finders.find(path)).read_text()
                positions = {}
                extends = []
                for match in CLASS_DECLARATION.finditer(source):
                    name, base = match.group(1), match.group(2)
                    positions.setdefault(name, match.start())
                    if base:
                        extends.append((name, base, match.start()))

                for name, base, at in extends:
                    self.assertIn(
                        base,
                        positions,
                        f"{path} declares `class {name} extends {base}` but "
                        f"never defines {base}: the bundle throws a "
                        f"ReferenceError on load. Add its file to this "
                        f"bundle's sources in scripts/minify_js.sh.",
                    )
                    self.assertLess(
                        positions[base],
                        at,
                        f"{path} defines {base} after {name} extends it; "
                        f"reorder the bundle sources so the base class "
                        f"comes first.",
                    )


class RowGenreClickReachesTheHeadingTests(SimpleTestCase):
    """A genre clicked in an album row has to reach the Alpine controls.

    `album-client-filtering.js` answers `add-genre` by writing the hidden
    `genres` select and re-rendering from the engine, which filters the list
    and pushes the URL. But `filters` lives on `mediaListControls`, and both
    the heading and the sidebar's genre tree are built from it - so setting
    the select alone filtered the list while the heading went on naming the
    unfiltered page. Reloading appeared to fix it, because the server then
    composed the heading from the URL.

    The two halves are in different files and neither reads the other, so
    this checks the event name still joins them up. A rename on one side
    only would leave the list filtering with a stale heading again, and
    nothing else in the suite would notice.
    """

    EVENT = "genres-selected"

    def _source(self, relative_path):
        path = Path(settings.BASE_DIR) / relative_path
        self.assertTrue(path.exists(), f"missing {relative_path}")
        return path.read_text()

    def test_the_row_handler_announces_the_selection(self):
        source = self._source("music/static/music/js/album-client-filtering.js")
        handler = source.split("'add-genre'", 1)
        self.assertEqual(len(handler), 2, "no add-genre handler to check")
        self.assertIn(
            self.EVENT,
            handler[1][:900],
            "the add-genre handler no longer announces the selection, so the "
            "heading and the genre tree will not follow it",
        )

    def test_the_controls_component_listens_and_updates_the_title(self):
        source = self._source("core/static/core/js/media-list-controls.js")
        self.assertIn(f"'{self.EVENT}'", source)
        listener = source.split("_genresSelectedListener = ", 1)
        self.assertEqual(len(listener), 2, "no listener to check")
        body = listener[1][:500]
        self.assertIn("filters.genres", body)
        self.assertIn("_applyTitle", body)

    def test_the_listener_is_registered_and_torn_down(self):
        source = self._source("core/static/core/js/media-list-controls.js")
        self.assertIn(f"addEventListener(\n                '{self.EVENT}'", source)
        self.assertIn(
            f"removeEventListener(\n                    '{self.EVENT}'", source
        )

    def test_the_minified_copies_carry_it(self):
        # The page loads the minified files, so a stale `.min.js` would ship
        # the bug with the fix sitting in the source beside it.
        for path in (
            "core/static/core/js/media-list-controls.min.js",
            "music/static/music/js/album-client-filtering.min.js",
            "music/static/music/js/music-client-side-filtering.bundle.min.js",
        ):
            with self.subTest(path=path):
                self.assertIn(self.EVENT, self._source(path))


class SavedFilterSortDirectionRoundTripsTests(SimpleTestCase):
    """A saved filter has to come back with the direction it went in with.

    Games stored `sortDirection` from the day saved filters shipped and
    never read it back, so applying a saved "Year, newest first" quietly
    returned it ascending. The bug was invisible from the server: the blob
    was correct in the database, and only the apply path dropped it.

    Pinned in source *and* minified form for both components, because the
    page loads only the minified copy - a fix that forgets `/minify` ships
    the bug with its own fix sitting beside it.
    """

    COMPONENTS = (
        "core/static/core/js/media-list-controls.js",
        "games/static/games/js/filter-component.js",
    )

    def _source(self, relative_path):
        path = Path(settings.BASE_DIR) / relative_path
        self.assertTrue(path.exists(), f"missing {relative_path}")
        return path.read_text()

    def test_each_component_writes_the_direction_when_applying(self):
        for relative_path in self.COMPONENTS:
            with self.subTest(component=relative_path):
                source = self._source(relative_path)
                applied = source.split("applySavedFilter(filter) {", 1)
                self.assertEqual(len(applied), 2, "no applySavedFilter to check")
                # The body ends at the next method; 2000 characters covers
                # the longest of the two by a wide margin.
                self.assertIn(
                    "filters.sortDirection",
                    applied[1][:2000],
                    "applySavedFilter no longer restores sortDirection, so a "
                    "saved filter loses its sort direction when applied",
                )

    def test_each_component_stores_the_direction_when_saving(self):
        # The other half of the round trip: restoring a key nothing saves
        # would be just as broken, and reads as correct in isolation.
        for relative_path in self.COMPONENTS:
            with self.subTest(component=relative_path):
                self.assertIn("sortDirection", self._source(relative_path))

    def test_the_minified_copies_carry_it(self):
        for relative_path in self.COMPONENTS:
            minified = relative_path.replace(".js", ".min.js")
            with self.subTest(component=minified):
                self.assertIn("sortDirection", self._source(minified))


class SavedFilterYearGridHookIsLiveTests(SimpleTestCase):
    """The shared year grid's saved-filter hook needs a flag to read.

    `core/includes/_year_grid.html` has always passed
    `isApplyingSavedFilter` behind a `typeof` guard, so a component without
    an `applyingSavedFilter` flag silently gets `false` and the grid treats
    a range mid-apply as a hover preview. The guard means the omission
    cannot throw, which is exactly why it needs a test.
    """

    def _source(self, relative_path):
        return (Path(settings.BASE_DIR) / relative_path).read_text()

    def test_the_grid_still_asks_for_the_flag(self):
        template = self._source("core/templates/core/includes/_year_grid.html")
        self.assertIn("isApplyingSavedFilter", template)
        self.assertIn("applyingSavedFilter", template)

    def test_the_subcomponent_consults_it(self):
        self.assertIn(
            "isApplyingSavedFilter",
            self._source("core/static/core/js/filter-subcomponents.js"),
        )

    def test_both_filter_components_define_the_flag(self):
        for relative_path in (
            "core/static/core/js/media-list-controls.js",
            "games/static/games/js/filter-component.js",
        ):
            with self.subTest(component=relative_path):
                self.assertIn(
                    "applyingSavedFilter:",
                    self._source(relative_path),
                    "the component defines no applyingSavedFilter, so the "
                    "year grid's guard resolves to false and the grid "
                    "previews a range while a saved filter is applied",
                )


class SavedFilterPartialsAreSharedTests(SimpleTestCase):
    """The saved-filter UI lives in core, and music is wired to it.

    Games keeps its own copy for now, deliberately. This records which of
    the two is on the shared partials, so the migration is a visible change
    rather than a silent drift.
    """

    PARTIALS = (
        "core/templates/core/includes/_saved_filters_dropdown.html",
        "core/templates/core/includes/_saved_filter_modals.html",
        "core/templates/core/includes/_mobile_saved_filters.html",
    )

    def test_every_shared_partial_exists(self):
        for relative_path in self.PARTIALS:
            with self.subTest(partial=relative_path):
                self.assertTrue((Path(settings.BASE_DIR) / relative_path).exists())

    def test_music_includes_all_three(self):
        pages = "".join(
            (Path(settings.BASE_DIR) / relative_path).read_text()
            for relative_path in (
                "music/templates/music/home.html",
                "music/templates/music/includes/_mobile_filter_sheet.html",
            )
        )
        for partial in (
            "core/includes/_saved_filters_dropdown.html",
            "core/includes/_saved_filter_modals.html",
            "core/includes/_mobile_saved_filters.html",
        ):
            with self.subTest(partial=partial):
                self.assertIn(partial, pages)

    def test_both_pages_bumped_their_cache_busters(self):
        """A one-way ratchet past the version that shipped without the fix.

        The `?v=` literals are hand-maintained, and both saved-filter
        changes live in files loaded that way: music gained the methods,
        games gained the `sortDirection` restore. Without a bump a
        returning reader keeps the cached copy, so the dropdown does
        nothing and the direction still goes missing.
        """
        for template, stale in (
            ("music/templates/music/home.html", "media-list-controls.min.js"),
            ("games/templates/games/home.html", "filter-component.min.js"),
        ):
            with self.subTest(template=template):
                page = (Path(settings.BASE_DIR) / template).read_text()
                match = re.search(re.escape(stale) + r"[\"']? %\}\?v=(\d+)", page)
                self.assertIsNotNone(match, f"{stale} is not loaded with a ?v=")
                self.assertGreater(int(match.group(1)), 3 if "media" in stale else 8)


class ApplyingASavedFilterMustNotAnnounceAResetTests(SimpleTestCase):
    """Applying a saved filter must not announce `year-reset`/`genres-reset`.

    Those two events do not mean "refresh yourselves". The mobile sheet's
    subcomponents answer them by clearing the state outright -
    `core/includes/_mobile_filter_time.html` assigns the full year range and
    `_mobile_filter_genres.html` assigns `[]` - and the sheet shares the
    rankings page's Alpine state at every width, desktop included.

    So dispatching them *after* restoring a stored combination wiped it:
    the sort and its direction survived, while the genre and the year range
    silently did not, and the heading went on naming the unfiltered page.
    Caught in a real browser, because every server-side test passed and the
    stored JSON was correct throughout.

    The selected state in both controls is derived from `filters`
    reactively, so neither needs telling.
    """

    RESET_EVENTS = ("year-reset", "genres-reset")

    def _apply_body(self, relative_path):
        source = (Path(settings.BASE_DIR) / relative_path).read_text()
        parts = source.split("applySavedFilter(filter) {", 1)
        self.assertEqual(len(parts), 2, f"no applySavedFilter in {relative_path}")
        # Up to the next method at the same indentation.
        body = parts[1]
        end = body.find("\n        },")
        self.assertNotEqual(end, -1, "could not find the end of applySavedFilter")
        # Comments are stripped, because the comment explaining *why* the
        # reset is not dispatched necessarily names the events.
        return "\n".join(
            line for line in body[:end].split("\n") if not line.strip().startswith("//")
        )

    def test_the_mobile_subcomponents_really_do_clear_on_reset(self):
        # The premise of the rule above. If these ever stop clearing state,
        # the rule stops being necessary and this suite should be revisited.
        time_sheet = (
            Path(settings.BASE_DIR)
            / "core/templates/core/includes/_mobile_filter_time.html"
        ).read_text()
        genre_sheet = (
            Path(settings.BASE_DIR)
            / "core/templates/core/includes/_mobile_filter_genres.html"
        ).read_text()
        self.assertIn('@year-reset.window="filters.start', time_sheet)
        self.assertIn('@genres-reset.window="filters.genres = []', genre_sheet)

    def test_neither_component_dispatches_a_reset_while_applying(self):
        for relative_path in (
            "core/static/core/js/media-list-controls.js",
            "games/static/games/js/filter-component.js",
        ):
            body = self._apply_body(relative_path)
            for event in self.RESET_EVENTS:
                with self.subTest(component=relative_path, event=event):
                    self.assertNotIn(
                        event,
                        body,
                        f"applySavedFilter announces {event}, which the "
                        f"mobile sheet answers by clearing the state the "
                        f"saved filter just restored",
                    )


class GamesGridIsClientRenderedTests(SimpleTestCase):
    """The games grid exists only once the bundle has built it.

    The server stopped rendering 100 hidden grid cards (~160 KB a page), so
    three things now have to hold or grid mode shows an empty list: the CSS
    hides the rows only when a grid exists, the page fetches the bundle at
    once for a reader in grid mode, and the filter component renders the
    grid as soon as the bundle is ready, filtered page or not. Each lives in
    a different file and nothing server-side exercises any of them.
    """

    def _read(self, relative_path):
        path = Path(settings.BASE_DIR) / relative_path
        self.assertTrue(path.exists(), f"missing {relative_path}")
        return path.read_text()

    def test_rows_are_hidden_only_once_a_grid_exists(self):
        for path in (
            "theme/static_src/src/styles.css",
            "theme/static/css/dist/styles.css",
        ):
            with self.subTest(path=path):
                css = self._read(path)
                self.assertIn(
                    "#game-list-container.view-grid:has(.game-grid) .game-row-wrapper",
                    css,
                )
                self.assertNotIn(
                    "#game-list-container.view-grid .game-row-wrapper", css
                )

    def test_grid_mode_fetches_the_bundle_at_once(self):
        page = self._read("games/templates/games/home.html")
        self.assertIn("localStorage.getItem('gameViewMode') === 'grid'", page)
        self.assertIn("pathFiltered || gridView ||", page)

    def test_the_component_renders_the_grid_when_ready(self):
        for path in (
            "games/static/games/js/filter-component.js",
            "games/static/games/js/filter-component.min.js",
        ):
            with self.subTest(path=path):
                source = self._read(path)
                self.assertIn("_needsClientGrid", source)
                self.assertRegex(source, r"\w+\._needsClientGrid\(\)")
                # The grid render keeps the URL: same filters as the server's.
                self.assertRegex(source, r"historyMethod:\s*null")
                self.assertIn(
                    "'grid-view'" if "min" not in path else '"grid-view"', source
                )


class ClientLoadMoreClaimsItsClickTests(SimpleTestCase):
    """A client-rendered Load More must load one page, not two.

    The button's own listener (filter-component.js / client-filtering.js)
    and utils-loadmore.js's delegated one on #game-results-container both
    answered the click, so every press of a client-rendered list's button
    appended two pages. Grid mode is always client-rendered now, which made
    that every grid reader's Load More.
    """

    def test_the_button_listeners_stop_the_click(self):
        for path in (
            "games/static/games/js/filter-component.js",
            "games/static/games/js/client-filtering.js",
        ):
            with self.subTest(path=path):
                source = (Path(settings.BASE_DIR) / path).read_text()
                handler = re.search(
                    r"button\.addEventListener\('click', \(event\) => \{(.{0,400})",
                    source,
                    re.S,
                )
                self.assertIsNotNone(handler, "Load More click handler changed")
                self.assertIn("event.stopPropagation();", handler.group(1))


class SharedPlayedMenuTests(SimpleTestCase):
    """Every played button opens the one #played-menu.

    The wrapper stops click propagation, so the mobile row it sits in does
    not navigate. The menu's listener therefore has to run in the capture
    phase, or it would never see a click on a button at all.
    """

    SOURCE = "games/static/games/js/played-menu.js"

    def test_the_minified_menu_is_findable(self):
        self.assertIsNotNone(finders.find("games/js/played-menu.min.js"))

    def test_the_click_listener_captures(self):
        source = (Path(settings.BASE_DIR) / self.SOURCE).read_text()
        listener = source.split("document.addEventListener('click'", 1)
        self.assertEqual(len(listener), 2, "no click listener")
        body = listener[1].split("document.addEventListener('keydown'", 1)[0]
        self.assertRegex(body.rstrip(), r"\}, true\);$")

    def test_the_post_inherits_the_csrf_header_from_the_wrapper(self):
        # htmx.ajax reads hx-headers from its source and the source's
        # ancestors, which is how the body's CSRF token reaches the POST.
        source = (Path(settings.BASE_DIR) / self.SOURCE).read_text()
        self.assertIn("source: wrapper, target: wrapper, swap: 'outerHTML'", source)


class LandingPagesPushOntoTheRankingsUrlTests(SimpleTestCase):
    """Filtering on a music landing page must not keep the landing path.

    The client used to push `?query` relative to the current path, so on
    `/music/genres/rock/` clearing the genre pushed `/music/genres/rock/`
    and a reload brought rock back. It now pushes onto
    `window.albumRankingsUrl`, and both popstate readers treat a landing
    page's bare path as the params it stands for.
    """

    def _source(self, relative_path):
        return (Path(settings.BASE_DIR) / relative_path).read_text()

    def test_the_url_push_uses_the_rankings_url(self):
        source = self._source("music/static/music/js/album-client-filtering.js")
        push = source.split("pushUrl(filters) {", 1)[1][:1400]
        self.assertIn("window.albumRankingsUrl", push)
        self.assertNotIn("query ? `?${query}`", push)

    def test_both_popstate_readers_know_the_landing_path(self):
        filtering = self._source("music/static/music/js/album-client-filtering.js")
        self.assertIn("window.albumLandingSearch", filtering)
        self.assertIn("const params = albumUrlParams();", filtering)
        controls = self._source("core/static/core/js/media-list-controls.js")
        sync = controls.split("_syncFromUrl() {", 1)[1][:700]
        self.assertIn("settings.landingSearch", sync)

    def test_the_minified_copies_carry_it(self):
        for path, needle in (
            ("music/static/music/js/album-client-filtering.min.js", "albumRankingsUrl"),
            (
                "music/static/music/js/music-client-side-filtering.bundle.min.js",
                "albumLandingSearch",
            ),
            ("core/static/core/js/media-list-controls.min.js", "landingSearch"),
        ):
            with self.subTest(path=path):
                self.assertIn(needle, self._source(path))

    def test_the_pages_bumped_their_cache_busters(self):
        # One-way ratchet past the versions that shipped the relative push.
        page = self._source("music/templates/music/home.html")
        for stale, shipped in (
            ("media-list-controls.min.js", 4),
            ("music-client-side-filtering.bundle.min.js", 3),
        ):
            with self.subTest(stale=stale):
                match = re.search(re.escape(stale) + r"[\"']? %\}\?v=(\d+)", page)
                self.assertIsNotNone(match, f"{stale} is not loaded with a ?v=")
                self.assertGreater(int(match.group(1)), shipped)


class MusicHighlightScrollsOnLoadTests(SimpleTestCase):
    """A `?highlight=` link from album detail must land on the album.

    The server marked the row highlighted, but nothing on the music page
    scrolled to it, and an album past the first hundred was not rendered at
    all. The games page has always done both; music now does too, from the
    bundle, so the minified copies have to carry it.
    """

    SOURCE = "music/static/music/js/album-client-filtering.js"

    def _source(self, relative_path):
        return (Path(settings.BASE_DIR) / relative_path).read_text()

    def test_the_highlight_is_read_and_scrolled_to_on_load(self):
        source = self._source(self.SOURCE)
        init = source.split("function initAlbumFiltering() {", 1)[1]
        self.assertIn("const highlightOnLoad = currentHighlight();", init)
        self.assertIn("scrollToAlbumById(highlightOnLoad, ", init)

    def test_an_album_past_the_rendered_rows_is_paged_down_to(self):
        source = self._source(self.SOURCE)
        init = source.split("function initAlbumFiltering() {", 1)[1]
        self.assertIn("await loadAlbumsThrough(csf, position);", init)

    def test_the_minified_copies_carry_it(self):
        for path in (
            "music/static/music/js/album-client-filtering.min.js",
            "music/static/music/js/music-client-side-filtering.bundle.min.js",
        ):
            with self.subTest(path=path):
                minified = self._source(path)
                self.assertIn("scrollToAlbumById", minified)
                self.assertIn("loadAlbumsThrough", minified)

    def test_the_page_bumped_the_bundle_cache_buster(self):
        page = self._source("music/templates/music/home.html")
        match = re.search(
            r"music-client-side-filtering\.bundle\.min\.js[\"']? %\}\?v=(\d+)", page
        )
        self.assertIsNotNone(match)
        self.assertGreater(int(match.group(1)), 4)
