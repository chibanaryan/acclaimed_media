# AGENTS.md (Canonical)

Last synchronized: 2026-10-18

This file is the canonical instruction source for Codex in this repository.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Acclaimed Games is a video game ranking and aggregation website that combines data from multiple sources to create comprehensive rankings. The application uses Django with server-side rendering, HTMX for dynamic interactions, and Alpine.js for client-side reactivity. It integrates with the IGDB (Internet Game Database) API.

## Available Skills

Use these skills for common workflows:
- `/commit` - Commit and push to git (builds CSS, minifies JS, collects static, pushes to main)
- `/deploy` - Deploy to Heroku production (all commit steps + push to Heroku)
- `/minify` - Minify JavaScript files and regenerate bundles
- `/igdb` - Import IGDB game data
- `/wikipedia` - Fetch Wikipedia metadata and genres
- `/refresh-metadata` - Weekly metadata refresh (IGDB + Wikipedia)
- `/test` - Run tests with coverage
- `/icons` - Add Material Design Icons to the site (including subset font rebuilds)
- `/openlibrary` - Fetch book metadata from Open Library API
- `/music-metadata` - Fetch album metadata (Wikidata, Discogs, MusicBrainz, cover art)

Import the music ranking release with `python manage.py import_music_data`,
then populate its metadata with `/music-metadata`
(`python manage.py fetch_album_metadata`).

## Development Commands

### Backend (Django)

**Activate virtual environment:**

On macOS/Linux:
```bash
source venv/bin/activate
```

On Windows (Git Bash/PowerShell):
```bash
source venv/Scripts/activate
```

**Run development server:**
```bash
DEBUG=True python3 manage.py runserver
```

**Note:** Always include `DEBUG=True` when running the development server locally to enable template reloading, detailed error pages, and the Django Debug Toolbar.

**Database migrations:**
```bash
python3 manage.py migrate
python3 manage.py makemigrations
```

**Create superuser:**
```bash
python3 manage.py createsuperuser
```

**Sync production database to local SQLite:**
```bash
python3 manage.py sync_from_prod
```
Downloads all game data from production Heroku and loads it into local SQLite. Auth users are excluded - create a local superuser after syncing with `python3 manage.py createsuperuser`.

**Collect static files (before deployment):**
```bash
python3 manage.py collectstatic
```

### Heroku Commands

**Important:** When running commands on Heroku, use `--` after `run` to separate Heroku flags from the command:

```bash
# Run Django shell with a command
heroku run -- python manage.py shell -c "from games.models import Game; print(Game.objects.count())"

# Run a management command
heroku run -- python manage.py migrate

# Open interactive shell
heroku run -- python manage.py shell
```

## Architecture

### Backend Structure

- **acclaimedgames/** - Django project settings and main URL configuration
- **core/** - Shared infrastructure for multi-media support:
  - **models.py** - User model, abstract base classes (MediaItemBase, CreatorBase, ExternalDataBase, UserTrackingBase)
  - **mixins.py** - Shared view mixins (RobustPaginationMixin, HTMXPartialMixin)
  - **templatetags/core_filters.py** - Shared template filters
  - **templates/core/** - Shared templates (_pagination.html, _base_media_row.html)
  - **static/core/js/** - Base JavaScript renderer classes
- **games/** - Main Django app containing:
  - **models.py** - Core data models (Game, Developer, Platform, List, etc.)
  - **api/** - REST API with views, serializers, and URL routing
  - **views.py** - Django class-based views for all routes
  - **middleware.py** - HTMXPushURLMiddleware for HTMX history support
  - **templatetags/** - Custom template filters (game_filters.py)
  - **management/commands/** - Custom Django commands (e.g., `get_igdb.py`)
  - **tests/** - Comprehensive test suite (API, models, IGDB, imports, views, admin, utils)
  - **templates/** - Server-side templates with HTMX and Alpine.js
  - **static/** - Static files served by Django
- **books/** - Books app for book rankings (feature-flagged with `BOOKS_ENABLED`):
  - **models.py** - Book, Author, BookGenre, BookSeries, ReadBook, WantToReadBook, etc.
  - **api/** - REST API with views, serializers, and URL routing
  - **views.py** - Book-related views (BookHomePageView, BookDetailView, AuthorListView, etc.)
  - **openlibrary.py** - Open Library API client for book metadata
  - **hardcover.py** - Hardcover GraphQL API client (optional)
  - **book_metadata.py** - Unified metadata service combining multiple sources
  - **templatetags/book_filters.py** - Book-specific template filters
  - **management/commands/** - Book metadata commands (fetch_book_metadata.py)
  - **templates/books/** - Book templates
  - **static/books/js/** - Book list renderer and client-side filtering

- **music/** - Music app for album rankings (staff-only beta, unlinked from the main site):
  - **models.py** - Album, Artist, MusicGenre, MusicPublication, MusicList, AlbumListMembership
  - **api/** - REST API with views, serializers, and URL routing (read-only, staff-only, deliberately uncached)
  - **views.py** - Album/artist/source-list views, all behind `core.mixins.StaffOnlyMixin`
  - **services/import_handler.py** - Imports the three-TSV album ranking release
  - **templatetags/music_filters.py** - Music-specific template filters
  - **management/commands/import_music_data.py** - Loads the ranking release files
  - **templates/music/** - Music templates; album rows extend `core/includes/_base_media_row.html`

**Installed Apps:**
- `django.contrib.admin` - Admin interface
- `django.contrib.auth` - Authentication
- `django.contrib.contenttypes` - Content type framework
- `django.contrib.sessions` - Session management
- `django.contrib.messages` - Messaging framework
- `django.contrib.staticfiles` - Static file management
- `django.contrib.flatpages` - Flat pages framework for CMS content
- `django.contrib.sites` - Sites framework (used for multi-site support)
- `django.contrib.postgres` - PostgreSQL-specific features
- `rest_framework` - Django REST Framework
- `corsheaders` - CORS support
- `tailwind` - django-tailwind integration
- `theme` - Tailwind CSS theme app with DaisyUI
- `core` - Shared infrastructure (User model, abstract bases, mixins)
- `games` - Main game aggregation app with HTMX and Alpine.js
- `books` - Book rankings app (behind `BOOKS_ENABLED` feature flag)
- `music` - Album rankings app (staff-only beta)

**Middleware:**
- `django.middleware.security.SecurityMiddleware` - Security headers
- `whitenoise.middleware.WhiteNoiseMiddleware` - Static file serving in production
- `django.contrib.sessions.middleware.SessionMiddleware` - Session management
- `corsheaders.middleware.CorsMiddleware` - CORS headers
- `django.middleware.common.CommonMiddleware` - Common utilities
- `django.middleware.csrf.CsrfViewMiddleware` - CSRF protection
- `django.contrib.auth.middleware.AuthenticationMiddleware` - Authentication
- `django.contrib.messages.middleware.MessageMiddleware` - Messages
- `django.middleware.clickjacking.XFrameOptionsMiddleware` - Click-jacking protection
- `games.middleware.HTMXPushURLMiddleware` - HTMX history/URL push support
- `django.contrib.flatpages.middleware.FlatpageFallbackMiddleware` - Flat pages routing

### Data Models

Core Django models include:

- **Game** - Video games with ranking, IGDB integration, genres, platforms, and developers
- **Developer** - Game development entities with hierarchical parent-child relationships
  - Uses self-referential `parent` FK for ownership hierarchy
  - Root developers (parent=None) have slugs for URL routing (e.g., Nintendo, Valve)
  - Subsidiary developers (parent=Developer) are child entities (e.g., Nintendo EAD, Respawn)
  - Games link to developers via `Game.developers` M2M field
  - In IGDB's data model, all are "company" records - we add hierarchy on import
- **Platform** - Gaming platforms (PC, PS5, etc.)
- **Genre** - Game genres
- **Publication** - Magazines/websites that publish game lists
- **List/ListMembership** - Published rankings and game positions within them
- **Post** - Blog-style news posts with markdown support
- **Snippet** - Reusable text snippets

Books-specific models (behind `BOOKS_ENABLED` feature flag):

- **Book** - Book items with ranking, author, genre, and metadata integration
- **Author** - Book authors with hierarchical parent-child relationships (similar to Developer)
- **BookGenre** - Hierarchical book genres with path denormalization
- **BookSeries** - Book series with position tracking
- **BookListMembership** - Book positions within lists
- **ReadBook/WantToReadBook** - User tracking for books (like PlayedGame/WantToPlayGame)
- **WikipediaBookData** - Wikipedia metadata for books

Music-specific models (staff-only beta):

- **Album** - Albums with ranking, published artist credit, artists, genres, and Wikidata/MusicBrainz ids
- **Artist** - Recording artists with hierarchical parent-child relationships (bands, side projects)
- **MusicGenre** - Hierarchical music genres with path denormalization
- **MusicPublication/MusicList/AlbumListMembership** - Album rankings and positions within them
- **WikipediaAlbumData/DiscogsAlbumData/MusicBrainzAlbumData** - fetched metadata on
  `ExternalDataBase`, each with the `primary_…` OneToOne fast-path and the
  `unique_primary_…_per_album` partial constraint. All use `on_delete=SET_NULL`, so
  they survive the `Album.objects.all().delete()` every import performs and are
  re-adopted by external ID afterwards
- **AlbumCover** - the cover-art bytes at two sizes, keyed by the Cover Art Archive's
  own release MBID, image id and size rather than by album, so they also outlive an
  import
- **ListenedAlbum / WantToListenAlbum** - per-user tracking on
  `core.models.UserTrackingBase`, as books' pair is and games' predates. Each
  keeps a nullable `album` FK **and** the album's `wikidata_id`, because an
  import deletes every `Album`: the rows survive on `SET_NULL` and
  `music.services.user_tracking_service` re-adopts them by that id afterwards.
  Mutual exclusivity is enforced by the toggle view, not by a constraint -
  they are separate tables, so no one constraint spans them

### API Architecture

Django REST Framework powers the API at `/api/` with endpoints:
- `/api/games/` - List and search games
- `/api/games/search/` - Game search for navbar
- `/api/games/<slug>/` - Game details with lists appearances
- `/api/developers/` - List of all developers with games
- `/api/developers/<slug>/` - Developer details by slug
- `/api/developers/by-id/<igdb_id>/` - Developer details by IGDB ID
- `/api/lists/` - Source lists
- `/api/platforms/` - Gaming platforms
- `/api/genres/` - Game genres (also available at `/api/wikipedia-genres/` for backwards compatibility)
- `/api/meta/` - Metadata about the database
- `/api/unified-search/` - Unified search for games, developers, and series

Books API endpoints (behind `BOOKS_ENABLED` feature flag):
- `/api/books/` - List and search books
- `/api/books/search/` - Book search
- `/api/books/<slug>/` - Book details with lists appearances
- `/api/books/all/` - Bulk endpoint with gzip compression
- `/api/books/authors/` - List authors
- `/api/books/authors/<slug>/` - Author details with book list
- `/api/books/unified-search/` - Unified book search

Music API endpoints (staff-only):
- `/api/music/` - List and filter albums
- `/api/music/<slug>/` - Album details with list appearances
- `/api/music/search/` - Album search
- `/api/music/artists/` and `/api/music/artists/<slug>/` - Artists
- `/api/music/lists/` - Source lists
- `/api/music/genres/` - Music genres
- `/api/music/meta/` - Counts and year/decade distributions
- `/api/music/all/` - Every album in one payload, for client-side filtering
- `/api/music/unified-search/` - Albums and artists together, for the sidebar
  and mobile search boxes
- `/api/music/saved-filters/` and `/api/music/saved-filters/<pk>/` - a
  reader's saved filter combinations. The only endpoints in `music/api/`
  that **write**, so the only ones CSRF applies to

**Note:** these endpoints carry no `cache_page` decorator on purpose. `cache_page`
wraps `dispatch`, so it is consulted before permissions run and a staff response
would be replayed to anonymous callers, defeating `IsStaffOrHide`.

**Note:** every read view in `music/api/` and `books/api/` uses a
`StaffReadAPIMixin` that names `SessionAuthentication`. `REST_FRAMEWORK`'s
`DEFAULT_AUTHENTICATION_CLASSES` is empty project-wide, so a view declaring only
`permission_classes = [IsStaffOrHide]` sees a logged-in staff member as anonymous
and 404s. The books API shipped that way until 2026-10-17 - its whole read API
was unreachable from a browser - and the tests missed it because
`APIClient.force_authenticate` bypasses authentication entirely. Test staff API
access with a real session login.

### Shared ranking-page components

The games and album rankings pages render the same chrome from `core/`. They
had each grown their own, and the album page's was visibly poorer for it - a
row of decade chips instead of the year heatmap, a flat `<select>` where a
root genre and one of its styles looked identical, no view toggle, no
jump-to-rank, and row styling that had copied the games hover rules without
the hover.

| Shared piece | What it is |
|---|---|
| `core/includes/_media_list_controls.html` | sort dropdown, direction flip, list/grid toggle, jump-to-rank |
| `core/includes/_year_grid.html` | the year heatmap, with drag and shift+click ranges |
| `core/includes/_genre_filter.html` | the hierarchical genre tree |
| `core/includes/_mobile_filter_time.html`, `_mobile_filter_genres.html` | their bottom-sheet equivalents |
| `core/includes/_entity_sort_controls.html` | the sort control for entity lists (artists, source lists, developers) |
| `core/includes/_publication_group.html` | a publication's lists, collapsible, on a source-lists page |
| `core/includes/_list_type_group.html` | one group of list appearances on a detail page |
| `core/includes/_rank_distribution.html` | where the filtered items sit across the ranking |
| `core/includes/_search_box.html` | the standard search input, with its clear button |
| `core/includes/_tracking_button.html` | the three-state tracking dropdown, and `_tracking_button_template.html`, its clone twin |
| `core/includes/_status_filter.html`, `_mobile_filter_status.html` | the tracking status filter |
| `core/includes/_saved_filters_dropdown.html`, `_saved_filter_modals.html`, `_mobile_saved_filters.html` | saved filter combinations, in the sidebar and the sheet |
| `core/services/titles.py` | the heading's wording: `join_names`, `build_time_window` |
| `core/services/ranking.py` | `rank_distribution`, the chart's binning |
| `core/js/filter-subcomponents.js` | `yearGridComponent`, `genreFilterComponent` and their mobile forms |
| `core/js/media-list-controls.js` | `mediaListControls`, `entityListControls` |
| `core/js/media-search.js` | `createMediaSearchData`, for a section's search box |
| `core/js/media-tracking.js` | `MediaTracking`, which keeps the tracking id Sets current after a button swap |
| `core/js/media-list-controls.js` | also the saved-filter state and methods, inert without a `savedFiltersUrl` |

The templates are the contract. Each binds to an Alpine component exposing
`filters`, `genres`, `initialized`, `debouncedFilterUpdate()`,
`handleFilterChange()`, `updateSort()`, `toggleSortDirection()`, `viewMode`
and `setViewMode()`. Games satisfies it with `filterComponent`, which also
owns platforms, series, playtime and saved filters; music satisfies it with
`mediaListControls`, which writes the state into its HTMX form and announces
a `change`. **Add a control to the shared template, not to one page.**

Row and card styling is shared the same way but through CSS selector lists -
`.game-row, .media-row { ... }` - because each section's JavaScript queries
its own class names. One rule block, both families; a fourth copy of the
`.game-row` rules is what left album rows without a hover state.

Facet counts (the number beside a year cell or a genre row) are counted with
their own dimension left out, so an option never leads to an empty page:
`apply_album_filters(..., skip=("year",))` server-side and
`AlbumFilterEngine.facets()` in the browser. Both publish the same
`year-counts-update` / `genre-counts-update` events the subcomponents listen
for, so neither side knows which did the counting.

### Music client-side filtering

`/music/` filters in the browser. `/api/music/all/` returns the whole corpus
(500 albums, ~100 KB of JSON, 38 KB gzipped), the bundle holds it in
`sessionStorage` keyed by the data version the page renders into itself, and
`music/static/music/js/` filters, sorts and renders locally. There is no
IndexedDB layer and no `version/` endpoint: at this size neither pays for
itself.

It is progressive enhancement. The page is server-rendered and its HTMX sidebar
filters server-side on its own; the bundle suppresses those requests only once
it has data and a renderer, so a failed or slow bundle leaves a working page.
Load More, jump-to-rank and the list/grid toggle all work either way: the
engine seeds itself from what the server rendered (`attach()` and
`_syncRendererWithPage()`) rather than re-rendering the page on load.

Two payload fields exist to keep the client and the server agreeing exactly:

- `nn` is `name_normalized`, the `unidecode(name)` column the server's `q`
  searches alongside `name` and `artist_credit`. Sent rather than recomputed,
  because reimplementing unidecode in the browser would be a second copy of the
  rule that drifts.
- `ni` is the album's position in the server's own `Lower(name)` ordering. No
  JavaScript comparator reproduces a database collation: `localeCompare` files
  "Ágætis byrjun" next to the A's while SQLite sorts it past Z, and punctuation
  is weighted differently again. The client sorts alphabetically by this
  integer, which also stops local SQLite disagreeing with production Postgres.

The genre filter expands a selected genre to its descendants on both sides,
as `games.services.query_filters.apply_genre_filter` does: picking "Rock"
means rock, including the Discogs styles filed under it. `expand_genre_ids`
does it server-side and `AlbumFilterEngine._expandGenres` in the browser,
from the descendant ids the payload already carries.

The count beside a genre is a **distinct** count across that genre's whole
subtree, so it is exactly what selecting the row gives. Summing a root and
its children instead - which is what the shared tree does when a section does
not supply subtree counts - double-counts an album tagged both "Classical"
and "Modern Classical", and the sidebar claimed Classical had two albums when
it had one. Music passes `genre_counts_include_descendants` to turn the
summing off.

When changing the filters, re-run the parity check: for a spread of filter and
sort combinations, compare the engine's ordered ids against
`GET /music/?<same query>&partial=true`. Unit tests cannot catch a divergence
here, because both sides can be self-consistently wrong.

### Album tracking

`ListenedAlbum` / `WantToListenAlbum` mirror games' `PlayedGame` /
`WantToPlayGame`, with four deliberate differences:

- **The button is one shared partial.** Games and books each carry their own
  near-identical copy; `core/includes/_tracking_button.html` takes the verbs,
  icons and route as parameters and `music/includes/_listen_button.html` is a
  thin wrapper supplying music's. It resolves the route **positionally**
  (`{% url toggle_url_name item.id %}`) because `{% url %}` cannot take a
  dynamic kwarg name - so a section's toggle route must take the item's pk as
  its one positional argument. Games and books are unchanged and can migrate.
- **No inline sync script.** Both other sections ship a `<script>` *inside*
  every swapped partial, which mutates the global Sets and then deletes its
  own earlier copies so they do not pile up. `core/js/media-tracking.js` is
  one delegated listener instead, and a page registers what its scope means.
- **The toggle is atomic.** The delete and the write run in one transaction
  and the write is an `update_or_create` keyed on the `unique_together`, so a
  double-click cannot race into an `IntegrityError` - and a row orphaned by a
  reimport is re-adopted on the spot. The cache is dropped in
  `transaction.on_commit`, so a rolled-back write cannot clear it.
- **Nothing per-user goes in `/api/music/all/`.** That payload is held in
  `sessionStorage` keyed only on its version, so two people sharing a browser
  session share it. The client joins on the album pk, which the payload
  already carries, and the page renders `window.listenedAlbumIds` /
  `window.wantToListenAlbumIds` per request - so there is no new payload key
  and no `SCHEMA_VERSION` bump.

Two traps worth knowing, both of which only appear in a real browser and are
now pinned by `core/tests/test_media_tracking.py` and the source tests in
`music/tests/test_tracking.py`:

- **`htmx:afterSwap` is too early to read the new state.** With
  `hx-swap="outerHTML"` the swap *replaces* the target, so `detail.target` is
  by then the detached old element, still carrying its pre-swap
  `data-status`. `media-tracking.js` listens on `htmx:afterRequest` and takes
  the new status from the request's own `?status=`.
- **The client-side filter suppressor must only cancel GETs.**
  `album-client-filtering.js` cancels HTMX requests once the engine can answer
  them locally, with listeners on the form and on
  `#album-results-container`. Every row sits inside that container, so a
  row's toggle POST bubbles through the same listener - and cancelling it made
  the button do nothing at all, but only once the bundle had loaded, which is
  why it looked intermittent.

Two filter vocabularies, as games has: `?listened=yes|want|no` (multi-select,
comma-joined) for filtering, and `?status=listened|want|none` for the toggle.
`?listened=yes` reads correctly in a URL and `data-status="listened"` reads
correctly on an element; `music/config.py:LISTEN_STATUS_OPTIONS` maps the two
server-side and the scope registry in `media-tracking.js` does client-side.

Per-user cache keys cannot live in `CACHE_KEYS`, which is a flat tuple an
import iterates. They are templates in `PER_USER_CACHE_KEY_TEMPLATES`, dropped
by `caching.invalidate_listen_caches(user_id)` at the only three moments they
can go stale: a toggle, the reconnection pass after an import, and the bulk
command below.

**Marking a collection in bulk**, for importing listens matched elsewhere
(a RateYourMusic export, say) without several hundred web requests:

```bash
python manage.py mark_albums_listened --user <name> --ids Q212863,Q19003
python manage.py mark_albums_listened --user <name> --ids-file ids.txt --dry-run
```

The matching stays outside the command. Deciding that an export's
"E·MO·TION" is our "Emotion" is a judgement call for whoever is looking at
both lists; the command takes the Wikidata ids that judgement produced and
does only the database half, with the toggle's own semantics - one
transaction, `update_or_create` on the `unique_together`, any
want-to-listen row for the same album cleared, and the per-user caches
dropped on commit. An id already marked is left alone, so a mark the user
made themselves keeps its `created` timestamp, and ids are matched against
every id an album carries rather than just the primary one.

**The User admin shows all four tracking counts** (played, want to play,
listened, want to listen) with a read-only capped list of each. The counts
are correlated subqueries, not `Count("relation", distinct=True)`: four
multi-valued joins on one queryset multiply, and a user with 822 listened
albums and 178 want-to-listen rows produced 146k intermediate rows before
`distinct` collapsed them again.

### Saved filters

A reader who has built up a genre + decade + listen-status combination keeps
it by name. Games has had this since `SavedFilterSet`; music's was built as
**shared `core/` components with music wired to them**, the way album
tracking was - games is untouched and can migrate by swapping three
includes.

| Piece | Where |
|---|---|
| `core.models.SavedFilterSetBase` | abstract: user, name, `filters` JSON, created/modified, `-modified` ordering |
| `music.models.SavedAlbumFilterSet` | the concrete table; adds nothing |
| `core/includes/_saved_filters_dropdown.html` | the sidebar "Saved" menu |
| `core/includes/_saved_filter_modals.html` | save / rename / delete, one copy per page |
| `core/includes/_mobile_saved_filters.html` | the bottom sheet's collapsible equivalent |
| `core/js/media-list-controls.js` | the state and the eight methods, named as games' are |
| `/api/music/saved-filters/` | list, create, rename, delete |

The partials bind to a **method contract**, not to a page:
`loadSavedFilters`, `applySavedFilter`, `saveCurrentFilters`,
`submitSaveFilter`, `renameSavedFilter`, `submitRenameFilter`,
`deleteSavedFilter`, `confirmDeleteFilter`, plus `hasActiveFilters` and
`savedFilters*`. Both `mediaListControls` and games' `filterComponent`
expose exactly those names, which is what makes the migration a template
change. The whole feature is inert unless the page passes a
`savedFiltersUrl`, so a section that has not opted in renders no button.

Four things worth knowing before changing any of it:

- **Applying a saved filter must not announce `year-reset` or
  `genres-reset`.** Those events do not mean "refresh yourselves":
  `core/includes/_mobile_filter_time.html` answers `year-reset` by assigning
  the full year range and `_mobile_filter_genres.html` answers
  `genres-reset` by assigning `[]`, and **the mobile sheet shares the
  rankings page's Alpine state at every width, desktop included**. So
  dispatching them after restoring a combination wiped it: the sort and its
  direction survived while the genre and the years were silently dropped,
  and the heading went on naming the unfiltered page. The grid and the tree
  derive their selected state from `filters` reactively and need no
  telling. Pinned by
  `core/tests/test_static_bundles.py::ApplyingASavedFilterMustNotAnnounceAResetTests`.
- **`applyingSavedFilter` was a hook with nothing on the other end.**
  `core/includes/_year_grid.html` has always passed `isApplyingSavedFilter`
  behind a `typeof` guard, so a component without the flag silently got
  `false` and the grid treated a programmatic range as a hover preview.
  Defining it on `mediaListControls` lit the hook up with no template
  change - and the guard is why its absence could never throw.
- **This is music's first *write* endpoint**, so CSRF applies to
  `music/api/` for the first time; `StaffWriteAPIMixin` sits beside
  `StaffReadAPIMixin` to say which views that covers. An outsider gets
  **404**, not games' 403, because the section has to look absent. The
  ordinary Django test client does not enforce CSRF, so
  `music/tests/test_saved_filters.py` uses
  `Client(enforce_csrf_checks=True)` for the real answer.
- **Deliberately uncached**, and `music/config.py` says so where a reader
  would otherwise expect a `CACHE_KEYS` entry: the rows are per-user, read
  once when the dropdown first opens, and written by the person about to
  re-read them.

`SavedAlbumFilterSet` needs no reconnection pass after an import, unlike the
tracking models - a saved filter references genres by id, and an import
replaces albums, not genres.

**Games' `applySavedFilter` never restored `sortDirection`**, though
`submitSaveFilter` had always stored it, so applying a saved "Year, newest
first" quietly came back ascending. Fixed on both sides, and pinned in
source and minified form, because the page loads only the minified copy.

### Template Architecture

The application uses Django templates with server-side rendering:
- **Production**: Uses Django's cached template loader for optimal performance
- **Development**: Uses non-cached loaders for hot-reloading during development
- Templates configured in `settings.py` based on `DEBUG` mode
- Game templates are in `games/templates/`
- Book templates are in `books/templates/` (feature-flagged)
- Shared templates are in `core/templates/`

## Application Structure (Django + HTMX + Alpine.js)

The application uses Django templates with HTMX for dynamic interactions and Alpine.js for client-side reactivity.

### Views and Templates

- **games/** - Main Django app containing:
  - **views.py** - View functions for all routes
  - **urls.py** - URL routing configuration (in main acclaimedgames/urls.py)
  - **templates/** - Django templates organized by feature:
    - **base.html** - Main template layout with navigation
    - **games/** - Game list, detail, and search templates
    - **developers/** - Developer list and detail templates
    - **lists/** - Lists and results templates
    - **posts/** - Post/news templates
    - **pages/** - Static page templates
  - **templatetags/** - Custom template filters (game_filters.py)
  - **middleware.py** - HTMXPushURLMiddleware for HTMX history support

### Application Features

**Styling:**
- Uses Tailwind CSS v4 with DaisyUI v5 component library
- Light theme (lofi) as default with forest dark theme available via theme switcher
- Responsive design using Tailwind's mobile-first breakpoints (md:, lg:, etc.)
- Custom components defined in `theme/static_src/src/styles.css` using Tailwind's `@layer components`

**Template Filters:**
- `from_now` - Converts datetime to relative time (e.g., "2 hours ago")
- Custom utilities for formatting and string manipulation

**Routes:**
- `/` - Home page (games)
- `/games/` - Game list with filtering and search
- `/games/<slug>/` - Game detail view
- `/games/search/` - Game search endpoint (HTMX)
- `/developers/` - Developer list with game counts and hierarchy
- `/developers/<slug>/` - Developer detail view with subsidiary hierarchy and games
- `/lists/` - Published rankings list (with media_type filter)
- `/posts/` - News and blog posts
- `/page/<slug>/` - Static pages

Book routes (behind `BOOKS_ENABLED` feature flag):
- `/books/` - Book list with filtering and search
- `/book/<slug>/` - Book detail view
- `/authors/` - Author list with book counts
- `/authors/<slug>/` - Author detail view with books

Music routes (staff-only, and deliberately **not** linked from anywhere on
the main site - reach them by URL):
- `/music/` - Album rankings with HTMX search, year/artist/genre filters and sorting
- `/music/<slug>/` - Album detail with list appearances grouped by list type
- `/music/artists/` - Artist list with album counts
- `/music/artists/<slug>/` - Artist detail with ranked albums
- `/music/lists/` - The published source lists behind the rankings
- `/music/import/` - Staff import for the three release files
- `/music/<album_id>/toggle-listened/` - POST, `?status=none|want|listened`,
  answering with the re-rendered button for HTMX to swap
- `/music/cover/<release_mbid>/<image_id>-<size>.jpg` - Cover art served from our own
  store, cached a year and immutable

**Navigation:** `core/includes/_sidebar_nav.html` picks the sidebar links
from `media_type`, so each section has its own navigation while the common
bottom block stays shared. Music is not linked from the games chrome.

**Access:** every music view and API endpoint uses `core.mixins.StaffOnlyMixin`
or `core.permissions.IsStaffOrHide`, which raise 404 (not 403) for anyone else.
There is no feature flag: the staff gate is the single access mechanism, and the
section has no entry point in the sidebar, mobile nav or media switcher, so a
normal visitor has no way to discover it. Music is also kept out of
`sitemap.xml`. Add a nav entry (and a flag, if you want a kill switch) when the
section is ready to launch publicly. A POST is hidden too: `CsrfViewMiddleware`
rejects it before the view's mixin runs, so `CSRF_FAILURE_VIEW` points at
`core.views.csrf_failure`, which answers a failed check under `/music/` with 404
for anyone but staff. Test it with `Client(enforce_csrf_checks=True)`; the
ordinary test client skips CSRF.

**HTMX Integration:**
- Dynamic filtering without full page reloads
- Pagination for lists with smooth navigation
- Real-time search results
- Smooth form submissions

**Alpine.js Interactivity:**
- Client-side state management for UI components
- Dropdown menus, modals, and toggles
- Form validation and user interactions

### Middleware

**HTMXPushURLMiddleware**: Provides HTMX support for browser history:
- Pushes URLs to browser history when HTMX requests complete
- Maintains browser back/forward functionality with HTMX
- Uses `HX-Push-Url` header for selective history updates

### Google Analytics Integration

The site uses Google Analytics 4 (GA4) with custom HTMX tracking for comprehensive page view analytics:

**Implementation Location:** `games/templates/base.html`

**Standard Page Views:**
- gtag.js loads on every page via base template
- Tracks initial page loads and full navigation
- Property ID: `G-0591405Q89`

**HTMX Navigation Tracking:**
- Custom event listener on `htmx:afterSwap` tracks partial page updates as page views
- Includes full URL path with query parameters for granular tracking
- Captures filter changes, pagination, and search navigation
- Provides more detailed tracking than typical SPAs (tracks query parameter changes as distinct page views)

**Code Example:**
```javascript
document.body.addEventListener('htmx:afterSwap', function(event) {
    // Track HTMX navigation as page views
    if (window.gtag) {
        gtag('config', 'G-0591405Q89', {
            page_path: window.location.pathname + window.location.search
        });
    }
});
```

**Advantages over SPA Tracking:**
- Automatically tracks all filter state changes (e.g., `/games/search/?q=zelda` vs `/games/search/?q=mario`)
- No custom router configuration required
- Simpler implementation with more granular insights

### Development Notes

- Template reloading works in development via Django's non-cached template loaders
- In production, template caching is enabled for performance

### Home Page Client/Server Rendering Consistency

The home page game rankings use a **dual-rendering architecture** that requires careful coordination:

**How It Works:**
1. **Server-side rendering**: Django templates render game rows with actual data on initial page load
2. **Client-side rendering**: JavaScript clones `<template>` elements and fills them with data for filtered/paginated results
3. **Single source of truth**: The same Django templates (`_game_row_desktop.html`, `_game_row_mobile.html`) serve both purposes

**Template Structure:**
- When `game` context is provided → server renders with data
- When `game` is absent (inside `<template>` tags) → renders empty structure with `data-slot` attributes for JS

**Files That Must Stay In Sync:**

| Server-Side (Python/Django) | Client-Side (JavaScript) |
|----------------------------|--------------------------|
| `games/templates/games/includes/_game_row_desktop.html` | `games/static/games/js/game-list-renderer.js` |
| `games/templates/games/includes/_game_row_mobile.html` | (fallback string methods: `_renderDesktopRowString`, `_renderMobileRowString`) |
| `games/templatetags/game_filters.py` | `_platformFamilies`, `_familyInfo` objects |
| `music/templates/music/includes/_album_row.html` | `music/static/music/js/album-list-renderer.js` |
| `music/templates/music/includes/_album_card_grid.html` | `AlbumListRenderer._renderGridCard` |
| `games/templates/games/includes/_game_card_grid.html` | `GameListRenderer._renderGridCard` |
| `core/templates/core/includes/_base_media_row.html` | `core/static/core/js/base-renderer.js` |
| `core/templates/core/includes/_tracking_button_template.html` | `AlbumListRenderer._renderTrackingButtonDOM` / `TRACKING_SLOTS` |

Music renders one partial for both halves: `_base_media_row.html` takes a
`row_variant` of `'desktop'` or `'mobile'` so `music/home.html` can put each
half in its own `<template>`, which is what `BaseMediaListRenderer`
`_initTemplates` expects. The renderer declares the slots it fills in
`AlbumListRenderer.SLOTS`, and `music/tests/test_visual_regression.py` checks
the template still emits every one of them - **including when the row is
rendered with no album**, which is how a `<template>` is rendered. A slot
placed inside `{% if item.something %}` disappears from the clone and the
renderer silently has nowhere to write.

**When Modifying Game Rows:**
1. Update the Django template for server-rendered output
2. Update the JavaScript renderer's DOM-cloning logic (uses `data-slot` attributes)
3. Update the JavaScript fallback string-rendering methods to match
4. Ensure `PLATFORM_FAMILIES` and `FAMILY_INFO` constants match between Python and JS

**Key Data Slots:** `rank`, `global-rank`, `thumbnail`, `name`, `year`, `title-link`, `thumb-link`, `year-link`, `meta-row`, `platforms`, `genres`, `list-count`, `primary-developer`, `played-button`

**Testing:** After changes, verify both:
- Fresh page load (server-rendered)
- Filtered results (client-rendered via JS template cloning)

## IGDB Integration

The `games/igdb.py` module handles IGDB API integration with multiple optimization strategies:

### Features

**Field Expansion**: Reduces API calls by 3-5x by expanding cover and genre data in the main game query instead of making separate requests.

**Concurrent Requests**: Process multiple games simultaneously (up to 8 concurrent requests) for 4-8x speedup.

**Multi-Query Batching**: Fetch multiple games per API request (10-50 for free tier, up to 500 for Pro tier) for additional 3-5x speedup.

**Pro Tier Support**: Access IGDB Pro tier with 750x faster rate limits (3,000 req/sec vs 4 req/sec).

**Thread-Safe**: All caching and rate limiting is thread-safe for concurrent processing.

IGDB provides cover art, descriptions, developer information, and genres.

For detailed command usage, run `/igdb`.

## Forum (removed)

The community forum (django-machina) was removed on 2026-10-17; a hosted
provider will cover that need instead. Migration `0115_drop_machina_tables`
dropped its 14 tables, content types, permissions, the "Forum Moderators"
group and machina's `django_migrations` rows, so nothing of it remains in the
schema. `Publication.reputation_score` survives as staff-edited editorial
metadata, now display-only.

## Music Data Import

The album rankings come from three TSV files, the same shape the games importer
takes (`acclaimedgames/test_input_files/music/` holds the current release):

| File | Columns |
|---|---|
| `ListData.txt` | publisher, year, name, url |
| `WebRankings.txt` | rank, name, artist_credit, year, wikidata_ids |
| `ListPositions.txt` | tab-separated `listIndex:position` pairs, one row per album in rank order |

```bash
python manage.py import_music_data            # uses the checked-in release files
python manage.py import_music_data --dry-run  # report inferred list types, change nothing
python manage.py import_music_data --lists ... --albums ... --positions ...
```

The import replaces all music ranking data in one transaction. Two details differ
from the games files:

- **No list type column.** `infer_list_type()` derives A/D/E/M from each title.
  Decade and era wording is matched before all-time wording, and an unqualified
  title falls back to all-time, since every list in this corpus is retrospective.
  Check the printed classification and correct any list in the admin.
- **Artist credits may contain commas that are not separators.**
  `split_artist_credit()` splits on commas except for acts listed in
  `ARTISTS_WITH_COMMAS` (`Crosby, Stills & Nash` and friends).

Unranked lists record every member at rank 1, matching the games convention.

**An import re-adopts tracking rows.** It deletes every `Album`, which
orphans every `ListenedAlbum` / `WantToListenAlbum`, so `import_albums` runs
`music.services.user_tracking_service.reconnect_tracking_records` afterwards
and reconnects them by Wikidata id - normalising a secondary id to the
primary and merging two rows that now point at one album, earliest kept.
Without it a reimport would look exactly like losing everyone's collection.
The pass is behind a one-query existence check, so an untracked database
pays nothing.

**An import does not fetch metadata.** It replaces every `Album` row, and the
external data rows survive on `on_delete=SET_NULL` - they are re-attached by
external id only when `fetch_album_metadata` next runs and adopts them. Until
then the rankings render with placeholder artwork and no genre filter at all,
because the sidebar hides a filter with nothing in it. The games import page
has the same split (its "Metadata Operations" panel, with its own buttons);
music's import page shows what is missing and the command to run.

The import stamps `SiteMetadata` under the `music` key, which the rankings
heading reads as "Updated: ...". `SiteMetadata` is keyed per section, so
games and music carry their own dates.

A new release can introduce an act whose own name contains a comma - the 2026
release added "Tyler, the Creator" - which `split_artist_credit` would
otherwise break into two artists. `ARTISTS_WITH_COMMAS` is the list, and
`test_every_real_comma_credit_parses_as_expected` names the acts rather than
counting them, so the next one fails loudly instead of quietly splitting.

## Music Metadata Pipeline

Run `/music-metadata` (`python manage.py fetch_album_metadata`) after an import.
Every album carries a Wikidata QID, which supplies the Discogs and MusicBrainz
identifiers the other sources are keyed by, so nothing is matched on title.

Four passes, selectable, because their costs differ by two orders of magnitude:
Wikidata is ~25 batched requests (seconds), cover art ~1000 downloads (~18 min),
Discogs ~500 requests at 25/min anonymous (~23 min), and MusicBrainz ~500 at its
hard 1 req/sec cap (~9 min, opt-in via `--musicbrainz`). Set `DISCOGS_TOKEN` to
raise the Discogs limit; the client paces itself from the response headers either
way.

Decisions worth knowing before changing any of it:

- **A style's root is corrected in place.** `get_or_create_genre` used to
  return an existing genre row untouched, so a style first created under the
  wrong root kept it forever: "Alternative Rock" sat under Electronic for 68
  albums long after the resolution order was fixed, because the fix could not
  reach a row that already existed. It now re-parents a row whose root has
  changed, `level` and `path` with it.
- **Genres are our own vocabulary, voted on by three sources.**
  `music/services/genre_normalizer.py` names every genre the filter offers -
  16 roots and about 125 leaves - and classifies each source label as a leaf,
  an alias of one ("Glam" -> Glam Rock, "thrash metal" -> Thrash Metal), a
  root ("hip-hop", "rock music"), or a label dropped on purpose ("Vocal",
  "Classic Rock"). An unclassified label creates nothing. When every Discogs
  style became a row of its own the tree had 207 leaves, 73 of them holding a
  single album, and an unmapped style took its root from the album's own
  Discogs genres, which filed Bubblegum under Electronic and Son under Jazz.
  Discogs styles are the **base** and are kept whole. Wikidata P136 and
  MusicBrainz genres can only **add**: a leaf another source also names, a
  root two sources support, or a leaf for an agreed root with nothing under
  it. A stricter "two sources must agree" rule was tried and dropped real
  genres, because Wikidata names a single genre for over half the albums
  (*Purple Rain* lost Funk). Leaves held by fewer than `MIN_LEAF_ALBUMS` (3)
  albums are pruned, and their albums keep the root. Wikidata alone is no
  better a source: it has *more* distinct labels than Discogs (272 against
  222), and its P279 graph classified only 159 of 207 genre entities, put
  thrash metal under Rock, and left ska, dub and ambient unreachable.
- **The tree stays two levels and single-parent; hybrids tag extra roots.**
  `HYBRID_ROOTS` gives Folk Rock, Country Rock, Synth-pop and a few others a
  second root on the *album*, not a second parent on the genre, so *Harvest*
  is under Rock, Folk and Country, while the shared tree, `genre_tree.py` and
  the client payload keep assuming one parent.
- **Genres are rebuilt offline, corpus-wide.** The passes only store what
  they fetch. `python manage.py rebuild_album_genres` (run automatically at
  the end of `fetch_album_metadata`) derives every album's genres from the
  stored rows in seconds, with no network. `--dry-run --report` shows the
  diff, the pruned leaves and any unclassified label - a new release's new
  labels show up there and fail `RealVocabularyTests`. The rebuild renames
  an alias's row in place, so its id survives, and remaps
  `SavedAlbumFilterSet` genre ids that point at deleted rows.
- **Cover art is downloaded, not hotlinked.** The Cover Art Archive redirects to
  archive.org, which 500s on roughly one request in ten and has a few items
  broken outright, so a hundred-cover page broke visibly on every load. The bytes
  live in `AlbumCover` and `music.views.AlbumCoverView` serves them. Downloading
  doubles as verification, and there are three fallbacks: the release group's own
  art, then any release in the group (earliest first), then a MusicBrainz search
  by title and artist for albums whose Wikidata entity has no P436.

`Album.cover_image_url` keeps the remote URL for the API and Open Graph scrapers;
`Album.thumbnail` and `Album.image` are what the pages render and prefer the local
copy.

## Music and games query budgets

`/music/` cost 443 queries and `/music/artists/` 305, measured against the
1000-album corpus. Both were one-shape N+1s, and both are now pinned by
`music/tests/test_views.py::MusicQueryBudgetTests`:

| page | before | after |
|---|---|---|
| `/music/` | 443 | 26 |
| `/music/?genres=<root>` | 439 | 16 |
| `/music/artists/` | 305 | 6 |
| `/api/music/all/` | 1218 | 10 |

- **`core/services/genre_tree.py` answers the hierarchy in one query.**
  `descendants_by_id(pairs)` maps every genre id to the ids below it from a
  single `(id, parent_id)` fetch. `MusicGenre.get_descendant_ids` still
  exists for one-off use, but nothing on a hot path calls it:
  `prefetch_related("children")` populates only the rows it fetched, so
  recursing into a child instance's own `children` is a query per node.
  The map is returned in **arrival** order, not the post-order the walk
  resolves nodes in, because callers iterate it to build the counts dict
  the page serializes - and that dict's order has to stay the manager's.
  It carries a cycle guard.
- **Deliberately uncached, in both sections.** Music's needs the whole
  table, where ~200 round trips to the shared cache lose to one SELECT of
  200 two-column rows. Games used to cache descendant ids per genre with
  signal invalidation, and that cache went stale: the filter's key
  (`genre_descendants:<id>`) was not one the signal deleted (`:<id>:True` /
  `:False`), so a re-parented genre filtered by its old tree for 24 hours.
  In production the shared cache is itself a Postgres table, so a hit costs
  a query anyway. `games.services.query_filters.genre_descendant_map()` is
  now one uncached SELECT of ~60 rows, and the signal is gone.
- **`ArtistListView` prefetches `albums` with the MusicBrainz row joined.**
  Needed because both row halves read `artist.albums.first` - the mobile
  card block runs it a second time, which is why it was 200 album selects
  for 100 rows. `{% with best=artist.albums.first %}` does resolve off the
  prefetch cache (measured), so no template change was needed.
- **`/api/music/all/` had the worst N+1 on the site and nothing recorded
  it**: the album loop reads `album.thumbnail` while the queryset prefetched
  only `artists` and `genres`, so 1000 albums each lazy-loaded their
  MusicBrainz row.
- **Add a filter dimension here and the facet passes multiply.** Build the
  map once per request - `AlbumHomePageView._descendants` and games'
  `HomePageView._genre_descendants` - and pass it in; every consumer
  (`apply_genre_filter` included) takes an optional `descendants=` and
  builds its own only when called standalone.
- **Games' `/` is pinned by
  `games/tests/test_main_views.py::GamesHomeGenreQueryBudgetTests`.** On a
  cold cache it cost 109 queries, 75 of them `games_wikipediagenre`:
  `get_landing_genres` filters once per root genre, and every filter walked
  `children` a query per node. Now 38, and `/?genres=<root>` 109 -> 39.
  `/api/games/all/` uses `descendants_by_id` too, in place of its own copy
  of the walk.

## The rankings heading and the tab title

Both sections compose a heading from the filter state and reuse it as the
document title. Three traps, all of which have bitten:

- **A genre clicked in a row does not go through the filter component.**
  `album-client-filtering.js` answers `add-genre` by writing the hidden
  select and re-rendering from the engine. `filters` lives on
  `mediaListControls`, and the heading and the sidebar genre tree are both
  built from it, so the row handler announces `genres-selected` and the
  component listens. Without that the list filtered while the heading went
  on naming the unfiltered page, and a reload "fixed" it because the server
  composes the heading from the URL. Games has no such bug: it routes
  `add-genre` through `component.addGenre`.
  `core/tests/test_static_bundles.py` pins the event name from both ends,
  minified copies included.
- **The document title is not free on either path.** `games/home.html` used
  `seo_title`, which only the SEO landing views set, so the tab title never
  moved. It now falls back to `filter_title`, as music's always did. Nothing
  set `document.title` during client-side filtering in either section;
  `base.html` publishes one `window.documentTitleSuffix` and both filter
  components rebuild `heading + suffix`.
- **The script cache-busters are hand-maintained.** `filter-component.min.js`
  and `media-list-controls.min.js` are loaded with `?v=N` literals. A JS fix
  that does not bump them reaches nobody who has visited before.

## Caching

Three aliases, defined by `core/cache_config.py` (which `settings.py` calls):

- **`default` is shared across processes.** In production it is Django's
  `DatabaseCache` on the existing Postgres (`CACHE_URL=dbcache://cache_table`),
  so the gunicorn workers and any one-off dyno see the same entries. That
  is what makes `music.views._invalidate_music_caches()` mean anything: under
  `LocMemCache` each process had its own copy and an invalidation reached
  exactly one of them, so a metadata refresh left stale filter options behind
  for up to their 24-hour TTL. Local dev stays on LocMem; `createcachetable
  cache_table` runs in the Heroku release phase and is idempotent.
- **`local` is per-process, and must stay that way.** It holds the whole
  rendered pages of `core.mixins.AnonymousResponseCacheMixin`. They are large
  and need no cross-process agreement: on the shared backend a crawler would
  push every page's HTML into Postgres and cull the small shared entries
  straight back out. The bodies are stored **deflated** - the rankings page is
  ~1.4 MB of HTML and there are ~50 cacheable URLs between the home page and
  the SEO landing pages, which uncompressed is 60-70 MB in every worker.
  A cached page's **CSRF token cannot be cached with it**. It is masked from
  the secret in one visitor's cookie, so replaying it hands the next visitor a
  token their own cookie will not match - and a cache hit renders no template,
  so nothing calls `get_token` and no cookie is set at all. `base.html`'s
  contact form therefore 403'd for anyone whose first page was a cached one.
  The mixin swaps the token for a NUL-delimited sentinel on the way in and
  mints a fresh one per request on the way out, so the page stays cacheable
  and the secret stays per-visitor. A page gaining a second independent token
  would need more than the single `replace`.
- **`ratelimit` is per-process too**, and holds the per-IP counters in
  `games.middleware`. It was carved out of `local` on 2026-10-18: page bodies
  and counters were culling each other out of one 500-entry LocMem, so a crawl
  wide enough to matter evicted the counters meant to stop it.

`MAX_ENTRIES` is set explicitly for all three, since Django's default of 300
culls a third of the cache on almost every write.

**There is deliberately no site-wide `UpdateCacheMiddleware` /
`FetchFromCacheMiddleware`.** Every page varies on `Cookie` - the auth-aware
chrome and the CSRF token see to that - so Django keyed a separate copy of
every page on every visitor's cookie header, while storing nothing at all for
a first-time visitor who has none (it skips the write when the response sets
cookies and the request carried none). Three workers' worth of per-visitor
HTML, at 1.4 MB each for any client that did not send `Accept-Encoding: gzip`,
was most of why the dyno sat over its 512 MB quota. See "Production memory
budget" below.

Music's cache keys all live in `music/config.py` as `CACHE_KEYS`, which
`_invalidate_music_caches()` iterates - add a cached value there or it will not
be invalidated. Every key carries `CACHE_VERSION`, so bumping that string
invalidates the whole set.

`/music/cover/` is exempt from rate limiting (`RATE_LIMIT_EXEMPT_PREFIXES`): it
is a static asset in all but the URL, and one rankings page requests up to a
hundred of them against a 120/minute budget.

## Production memory budget

The web dyno is a Basic one: **512 MB for every gunicorn worker together**.
Measured on 2026-10-18, one worker boots at ~110 MB (79 MB of imports, ~30 MB
of it `sentry_sdk`) and plateaus at **~200 MB** once it has rendered a page or
two - flat from ~50 renders out to 1000, so there is no leak to hunt. The
rankings page is 1.4 MB of HTML, and the ~45 MB a worker never returns after
its first render is allocator arenas, not live data.

That arithmetic sets the shape of the `Procfile`:

- **`--workers 2`.** 2 x 200 MB leaves ~110 MB of headroom; three workers
  needed ~570 MB and the dyno had been swapping and firing R14 all day.
- **No `--preload`.** Measured with a fork test: a child touched ~160 MB of
  the parent's pages within 20 requests, because CPython refcounts dirty the
  page holding every object they read. Copy-on-write saved nothing (593 MB
  preloaded vs 585 MB not).
- **`--timeout 600` stays.** The games importer streams progress over SSE and
  a shorter timeout kills that mid-import.
- `--max-requests 500` is a guard against slow growth, not a memory lever: a
  recycled worker is back at the plateau within ~15 page renders.

**Template indentation is stripped at load.** `core/template_loaders.py`
wraps both loaders, in dev and prod alike, and removes the leading whitespace
of every `.html` source line, which was 36% of the rankings page. Each newline
survives, so rendering is unchanged, except inside `<pre>`/`<textarea>`, which
are left as written. **Do not add markup whose meaning depends on
indentation** - `white-space: pre` in CSS, or indented text in a `<code>`
block - without exempting it there.

Anything that grows the rendered page, the boot imports, or a per-process
cache is spending from that 512 MB twice over. `heroku ps`, and the
metrics API (`api.metrics.heroku.com/apps/<id>/formation/web/metrics/memory
?start_time=..&end_time=..&step=1h&process_type=web`, with
`memory.rss.bytes.max` and `memory.swap.bytes.max`), are how to check it.

## Configuration

### Environment Variables

Environment variables are managed via django-environ (`.env` file):
- `DEBUG` - Enable Django debug mode
- `SECRET_KEY` - Django secret key
- `IGDB_CLIENT_ID` - IGDB API client ID
- `IGDB_CLIENT_SECRET` - IGDB API client secret
- `IGDB_USE_PRO_TIER` - Enable IGDB Pro tier (default: False)
- `WIKIDATA_ACCESS_TOKEN` - For faster Wikipedia processing (2.5x speedup)
- `BOOKS_ENABLED` - Enable books feature (default: False, enabled in DEBUG/TEST modes)
- `HARDCOVER_API_TOKEN` - Optional Hardcover API token for additional book metadata
- `DISCOGS_TOKEN` - Optional Discogs personal access token; raises the music
  metadata rate limit above the 25 requests/minute anonymous tier
- `CACHE_URL` - Cache backend URL. Production uses `dbcache://cache_table`;
  local dev falls back to LocMem whatever this says, and tests set
  `locmemcache://`. See the Caching section

### Configuration Files

- **`.python-version`** - Specifies Python 3.11 for Heroku deployment (can use different versions locally)
- **`.pre-commit-config.yaml`** - Pre-commit hook configuration for code quality enforcement (Black, Flake8, tests)
- **`.coveragerc`** - Coverage configuration excluding migrations and database vendor-specific code
- **`.flake8`** - Flake8 linter configuration (max line length 88, excludes venv)
- **`scripts/run_tests.sh`** - Alternative test runner using Django's test framework

## Database

- **Development**: SQLite (`db.sqlite3`)
- **Production**: PostgreSQL on Heroku
- The `rank` field on Game determines primary ordering (lower is better)
- `year_rank` and `decade_rank` are derived from `rank` by
  `core.services.ranking.update_year_decade_ranks()`, which runs during import -
  **not** automatically on save

## Dependencies

The backend dependencies are listed in `requirements.txt` and include:
- **coverage** - Test coverage reporting tool
- **Django** and related packages - Web framework and extensions
- **django-tailwind** - Tailwind CSS integration for Django
- **djangorestframework** - REST API framework
- **psycopg2** - PostgreSQL database adapter
- And other supporting packages

**Note:** Tailwind CSS and DaisyUI are managed via npm in `theme/static_src/` (not Python packages).

Install all backend dependencies with:
```bash
pip install -r requirements.txt
```

## Static Files

- Django collectstatic copies static files from apps to `staticfiles/`
- WhiteNoise serves static files in production
- Static files are located in:
  - `games/static/` - Game app static files (icons, fonts, images)
  - `theme/static/` - Tailwind CSS compiled output
  - `games/templates/` - Template files

### CSS Workflow (Tailwind CSS)

The site uses django-tailwind with Tailwind CSS v4 and DaisyUI v5 for styling.

**Development:**
```bash
# Start Tailwind CSS watcher (rebuilds CSS on file changes)
python manage.py tailwind start

# Run Django dev server (in separate terminal)
python manage.py runserver
```

**Production Build:**
```bash
# Build minified CSS for production
python manage.py tailwind build

# Collect static files
python manage.py collectstatic --noinput
```

**File Locations:**
- `theme/static_src/src/styles.css` - Main Tailwind CSS source file with custom components
- `theme/static/css/dist/styles.css` - Compiled CSS output (auto-generated)
- `games/static/games/css/mdi-subset.css` - Material Design Icons (self-hosted subset)
- `games/static/games/fonts/materialdesignicons-webfont.woff2` - Generated MDI subset font

**Adding Custom Styles:**
Edit `theme/static_src/src/styles.css` and use Tailwind's `@layer` directive:
```css
@layer components {
  .my-component {
    @apply flex items-center gap-2;
  }
}
```

**DaisyUI Components:**
Common components used: `btn`, `card`, `table`, `alert`, `badge`, `input`, `select`, `checkbox`, `dropdown`, `modal`, `link`

**Theme Configuration:**
Themes are defined in `theme/static_src/src/styles.css` using DaisyUI's `@plugin` directive:
```css
@plugin "daisyui" {
  themes: ["lofi", "forest"];
}
```
The theme switcher in the navigation allows users to change themes, with the selection persisted in localStorage.

### MDI Subset Workflow

Material Design Icons are shipped as a local WOFF2 subset to reduce transfer size.

**Rebuild command:**
```bash
./scripts/build_mdi_subset.sh
```

**Dependencies:**
- `pyftsubset` (from `fonttools`)
- `brotli`
- `zopfli`

Install once if missing:
```bash
pip install fonttools brotli zopfli
```

The script scans icon codepoints from `games/templates/base.html` and `games/static/games/css/mdi-subset.css`, then rewrites `games/static/games/fonts/materialdesignicons-webfont.woff2` in place.

### JavaScript Workflow

JavaScript files in `games/static/games/js/` follow a specific workflow:

**Source and Minified Files:**
- Source files (e.g., `game-list-renderer.js`) contain the readable code
- Minified files (e.g., `game-list-renderer.min.js`) are generated from source files
- **Always edit the source `.js` file, never the `.min.js` file directly**

**Bundle Files:** three, each built by `scripts/minify_js.sh` from minified
sources in dependency order, and each starting with
`core/static/core/js/base-renderer.min.js` - a bundle whose renderer extends
`BaseMediaListRenderer` without it throws a `ReferenceError` as it loads, so
nothing declared after that point registers either:

- `games/static/games/js/client-side-filtering.bundle.min.js` - `base-renderer`, `game-cache`, `client-filter`, `game-list-renderer`, `client-filtering`
- `books/static/books/js/book-client-side-filtering.bundle.min.js` - `base-renderer`, `book-cache`, `book-client-filter`, `book-list-renderer`, `book-client-filtering`
- `music/static/music/js/music-client-side-filtering.bundle.min.js` - `base-renderer`, `album-filter`, `album-list-renderer`, `album-client-filtering`

`core/static/core/js/` also holds three files loaded on their own rather than
bundled, because they have to run before Alpine initialises:
`filter-subcomponents.min.js`, `media-list-controls.min.js` and
`media-search.min.js`. Pages push them onto `window.alpineScripts` in
`{% block pre_alpine %}`.

`core/tests/test_static_bundles.py` asserts that every bundle a template
references exists and that each defines the base classes its members extend.
Both of those failed silently in the books bundle until 2026-10-17.

**After Editing JavaScript:**
Run `/minify` or `./scripts/minify_js.sh`

The minify skill/script:
1. Minifies any source `.js` files that are newer than their `.min.js` counterparts
2. Regenerates the bundle if any of its source files changed
3. Stages updated files for git

**Important:** When modifying client-side game rendering (e.g., `game-list-renderer.js`), changes must be reflected in both:
- The Django template (server-side rendering)
- The JavaScript file (client-side rendering on home page)

## Design Guidelines

### Quantitative Display Ruleset

When making any changes that affect **visual displays of quantitative information** (charts, graphs, tables with numbers, rankings, statistics, data visualizations), read and follow the principles in:

**`acclaimedgames/rulesets/Unified Quantitative Display Ruleset.md`**

This ruleset applies to:
- Game ranking displays and tables
- Statistics and metrics (play counts, list appearances, scores)
- Charts or graphs showing trends, distributions, or comparisons
- Any numerical data presentation to users

Key principles to prioritize:
- **Graphical integrity**: Represent quantities proportionally; what is shown must match the data
- **Data-ink ratio**: Maximize data-bearing elements, minimize decorative non-data elements
- **Comparison support**: Design to encourage meaningful comparisons
- **Context**: Always provide units, time frames, and context needed for interpretation
- **Avoid chartjunk**: No fake 3D, unnecessary decoration, or design that doesn't serve the data
