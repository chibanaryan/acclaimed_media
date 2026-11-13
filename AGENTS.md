# AGENTS.md

This file provides guidance to Claude Code and Codex when working with code in this repository.

`CLAUDE.md` is a symlink to this file: edit this one, and keep the link. Claude Code would load this file without it, but `/code-review`'s conventions check reads only `CLAUDE.md` files (checked 2026-10-31, Claude Code 2.1.309), so deleting the link stops the review checking the rules below.

**How this file is organised.** It holds the rules, and a map. The reasoning,
history and measurements behind each section are in `docs/agents/<topic>.md`,
named under each heading here (they were this file's own text until
2026-11-12, when it had reached 200 KB and loaded into every session).
**Read a section's file before changing the code it describes**: the rules
here say what to do, and the files say what went wrong the last time someone
did otherwise. A rule a review should enforce belongs here, since the review
reads only this file; an account of why belongs there.
`core/tests/test_agent_instructions.py` fails on a pointer to a file that
does not exist.

## Project Overview

Acclaimed Media ranks the most critically acclaimed video games and albums by aggregating critics' lists. One Django app serves three hosts: a landing page at `acclaimedmedia.org`, the game rankings at `games.acclaimedmedia.org` and the album rankings at `music.acclaimedmedia.org` (see "Domain"). The application uses Django with server-side rendering, HTMX for dynamic interactions, and Alpine.js for client-side reactivity. It integrates with the IGDB (Internet Game Database) API.

## Available Skills

Use these skills for common workflows:
- `/commit` - Commit and push to git (builds CSS, minifies JS, runs `/code-review`, pushes to main)
- `/deploy` - Deploy to Heroku production (all commit steps, review included, then waits for CI, backs up the database if migrations ship, pushes to Heroku and checks `/healthz/`)
- `/minify` - Minify JavaScript files and regenerate bundles
- `/igdb` - Import IGDB game data
- `/wikipedia` - Fetch Wikipedia metadata and genres
- `/refresh-metadata` - Weekly metadata refresh (IGDB, Wikipedia and HLTB)
- `/test` - Run tests with coverage
- `/icons` - Add Material Design Icons to the site (including subset font rebuilds)
- `/openlibrary` - Fetch book metadata from Open Library API
- `/music-metadata` - Fetch album metadata (Wikidata, Discogs, MusicBrainz, cover art)
- `/upgrade-deps` - Monthly upkeep: Dependabot PRs, package bumps, audits, performance and end-of-life checks

Import the music ranking release with `python manage.py import_music_data`,
which then fetches the metadata it left missing (`/music-metadata`,
`python manage.py fetch_album_metadata`).
`python manage.py import_games_data` loads the games release from the
command line, as the staff import page does, then fetches IGDB, Wikipedia and
HLTB for the games missing them. Both default to the files
in `acclaimedgames/test_input_files/`, and `--no-metadata` skips the fetch
(see "Music Data Import").

### Review before merging

Every ticket's changes get a `/code-review` pass (at `high`) before they
reach `main`. Pushing to `main` is the merge here: there is no branch
protection, and the only PRs are Dependabot's, so the review is a workflow
rule rather than a GitHub one. `/commit` and `/deploy` run it as their step
5. A hand-run `git push origin main` or merge is covered by the same rule,
and so is merging a Dependabot PR with `gh pr merge`.

Round 1 reviews the whole diff. Sort every finding, and say in chat what
became of each:

- **Blocker:** this change causes wrong behaviour a reader can reach, data
  loss, a crash or a security hole. Fix it, with a test that fails first.
- **Older bug:** already on `main`. Not a blocker. List it for its own
  ticket, unless it is a line or two in code this change already touches.
- **Cleanup or test gap:** fix it in round 1 or waive it. It never starts a
  round.

Review again only if a blocker fix changed code, and only that fix (name the
files it touched as the target). Stop when a round has no blockers. Stop and
ask the user if a third round still has blockers, if a fix breaks something
an earlier round covered, or if the diff has outgrown the request. Until
2026-11-01 any change restarted the review of the whole diff: one ticket
of three small fixes ran ten rounds and 71 findings, most of them cleanups,
and about eight of them regressions from fixes made for earlier findings.

Run focused tests between rounds, and the full suites and browser checks once,
at the end. Skip the review only when the user says to, or the diff touches
no code or templates (a Dependabot PR that changes only lock files touches
none). Codex has no `/code-review`: a Codex session asks the user before
pushing to `main` or merging a PR.

## Development Commands

### Backend (Django)

**Activate virtual environment:** `source venv/bin/activate` (Windows:
`source venv/Scripts/activate`).

**Run development server:**
```bash
DEBUG=True python3 manage.py runserver
```

Always include `DEBUG=True` locally: template reloading, detailed error
pages, the Debug Toolbar, and the `*.localhost` hosts.
Open `http://games.localhost:8000/` for the games site, `http://music.localhost:8000/` for music and `http://localhost:8000/` for the landing page (see "Domain"). `127.0.0.1:8000` serves the games site.

**Database migrations:** `python3 manage.py migrate`, `python3 manage.py makemigrations`.

**Create superuser:** `python3 manage.py createsuperuser`.

**Sync production database to local SQLite:** `python3 manage.py sync_from_prod`
downloads the games and music data from production Heroku (two `dumpdata`
runs, ~100 MB with the cover art, a few minutes). Per-user rows are not
synced and local ones are deleted; auth users are excluded, so local accounts
survive. It refuses any database but SQLite, and a dyno: it deletes every
game and album from whatever database is configured, and
`.env.development.local` beats the shell. A failure exits non-zero.

**Other commands worth knowing** (each has `--help`): `repair_email_rows`
lists accounts whose allauth address rows disagree with their email, and
`--sync <username>` repairs one (see "Domain"); `populate_platform_years`
re-applies `games/platform_years.py` to the platforms after editing it;
`clear_music_caches` drops music's caches after a cache error; and
`mark_albums_listened --user <name> --ids Q1,Q2` marks a collection in bulk
(see "Album tracking").

**Collect static files (before deployment):** `python3 manage.py collectstatic`.

### Heroku Commands

Use `--` after `run` to separate Heroku's flags from the command:

```bash
heroku run -- python manage.py shell -c "from games.models import Game; print(Game.objects.count())"
heroku run -- python manage.py migrate
```

`manage.py shell` never reports to Sentry, on a dyno either, and that
includes `heroku run:detached`: unwatched work belongs in a command.

## Architecture

### Backend Structure

Full text, with every installed app and each middleware's reason: `docs/agents/backend-structure.md`.

- **acclaimedgames/** - project settings; the URLconfs `urls_root.py`,
  `urls_games.py`, `urls_music.py`, with the shared routes in `urls_common.py`
- **core/** - shared infrastructure: `sites.py` and `middleware.py` (the
  three sites by host), `views.py` (landing page, the apex's redirects,
  `healthz`), `models.py` (User, the abstract bases), `mixins.py`,
  `templatetags/core_filters.py`, `templates/core/includes/` (the shared
  partials), `static/core/js/` (the base renderer and shared components),
  `services/` (query parameters, search ranking, SEO, the post-import
  fetch, cache helpers)
- **games/** - `models.py`; `api/`; `views/`, one module per page family
  (`rankings`, `game_pages`, `developers`, `lists`, `download`, `content`,
  `imports`, `auth`, plus `filter_titles` and `_helpers`), with `__init__`
  re-exporting every name; `services/`; `middleware.py`; `templatetags/`;
  `management/commands/`; `tests/`; `templates/`; `static/`
- **music/** - `models.py`; `api/`; `views.py`; `sitemaps.py`; `services/`
  (`landing_pages`, `import_handler`, `credits`, `metadata_service`,
  `caching`, ...); `templatetags/music_filters.py`; `management/commands/`;
  `templates/music/`, whose album rows extend
  `core/includes/_base_media_row.html`
- **books/** - book rankings, staff-only (`BOOKS_ENABLED` shows its nav
  links), parked: server-rendered, with no client engine since 2026-11-12

Rules:
- **Patch a name where it is read**, in the module that reads it
  (`games.views.rankings._get_year_bounds`), never where it is re-exported.
  `games/utils.py` re-exported the services until 2026-11-12; it holds the
  two emails now.
- The middleware order is deliberate: `SiteHostMiddleware` right after
  security, then the CSP middleware, WhiteNoise, the uptime-check shortcut,
  rate limiting and gzip, all ahead of sessions. Read the file before moving
  one.

### Data Models

Full text: `docs/agents/data-models.md`.

Games: `Game`, `Developer` (self-referential `parent`; roots have slugs),
`Platform`, `WikipediaGenre` (hierarchical), `Series`, `IGDBGameData` /
`WikipediaGameData` / `HLTBGameData`, `Publication`, `List` /
`ListMembership`, `PlayedGame` / `WantToPlayGame`, `SavedFilterSet`,
`Article`, `Post`, `SiteMetadata`, `Snippet`.
Music: `Album`, `Artist`, `AlbumCredit`, `MusicGenre`, `MusicPublication` /
`MusicList` / `AlbumListMembership`, `WikipediaAlbumData` /
`DiscogsAlbumData` / `MusicBrainzAlbumData`, `AlbumCover`,
`ListenedAlbum` / `WantToListenAlbum`, `SavedAlbumFilterSet`.
Books (staff-only): `Book`, `Author`, `BookGenre`, `BookSeries`,
`BookListMembership`, `ReadBook` / `WantToReadBook`, `WikipediaBookData`.

Rules:
- **A games import recreates every `Game`**; the fetched-metadata rows
  outlive it and are reattached. So anything that must survive an import
  lives on the metadata row, not on `Game` (the open-ended call on
  `HLTBGameData`, IGDB's `summary` on `IGDBGameData`), and games' tracking
  rows are keyed on the IGDB id.
- `Game.igdb_id` and `slug`, `Developer.igdb_id` and `slug`, and
  `Album.slug` are unique where set. A slug IGDB gives that another row
  holds is handed over (`Game._free_slug`; the developer's old holder moves
  to `<slug>-<its IGDB id>`).
- **Key a music tracking row on `Album.tracking_key`**, never on
  `wikidata_id`: the primary QID, or `pk:<id>` for an album with none.
- Read an album's artists through `album.credits.all()` or
  `album.credited_artists`, not `album.artists.all()`, which is alphabetical.
- "Have" is a `ListenedAlbum` row with `owned=True`, not a third table.
  Mutual exclusivity between the two tracking tables is the toggle view's.
- `year_rank` and `decade_rank` are derived by
  `core.services.ranking.update_year_decade_ranks()` during import, not on
  save. `rank` orders everything (lower is better).

### API Architecture

Full endpoint list and each endpoint's history: `docs/agents/api.md`.

Django REST Framework. Games at `/api/` on the games host (`games/`,
`games/search/`, `games/<slug>/`, `games/all/`, `developers/...`, `lists/`,
`publications/`, `platforms/`, `genres/` and `genres/tree/`, `snippets/`,
`pages/`, `meta/`, `unified-search/`, `saved-filters/`); music at `/api/` on
the music host (`/`, `<slug>/`, `search/`, `artists/`, `lists/`, `genres/`,
`meta/`, `all/`, `unified-search/`, `saved-filters/`); books under
`/api/books/` (staff).

Rules:
- **Every view in `music/api/` and `books/api/` names
  `SessionAuthentication`** (through `MusicReadAPIMixin`,
  `MusicWriteAPIMixin` or `StaffReadAPIMixin`).
  `DEFAULT_AUTHENTICATION_CLASSES` is empty project-wide, so a view that
  names none sees a signed-in user as anonymous. **Test API access with a
  real session login**: `APIClient.force_authenticate` bypasses
  authentication entirely.
- The saved-filter endpoints are each site's only writes: behind a session
  and CSRF, parsed by `core.services.request_body.SavedFilterJSONParser`
  (16 KB ceiling) and read through `read_saved_filter`, which never raises.
- Music's API carries no `cache_page`, deliberately (measured 2026-11-09).
  Games' kept answers are keyed on the release, the data version, the host
  and the bare path; a request with a query string is rendered, not kept.
- `/api/games/all/` is built by `games/services/all_data_payload.py`, for
  the view and for the weekly refresh's fingerprint. Nothing per-user goes
  in either site's `all/` payload.
- No artist pk is public: `?artists=` takes slugs, and no artist serializer
  has an `id`.
- A name is searched as typed or without its accents
  (`games.models.name_search_q`, `credits.album_search_q`); search results
  are ordered by `core/services/search_ranking.py` on both sites.

### Shared ranking-page components

Full text, with the year grid's fade: `docs/agents/ranking-components.md`.

The games and album rankings pages render the same chrome from `core/`:

| Shared piece | What it is |
|---|---|
| `core/includes/_media_list_controls.html` | sort dropdown, direction flip, list/grid toggle, jump-to-rank |
| `core/includes/_year_grid.html`, `_genre_filter.html` | the year heatmap; the hierarchical genre tree |
| `core/includes/_mobile_filter_time.html`, `_mobile_filter_genres.html` | their bottom-sheet equivalents |
| `core/includes/_entity_sort_controls.html` | the sort control for entity lists |
| `core/includes/_publication_group.html`, `_list_type_group.html` | source-list and detail-page groups |
| `core/includes/_rank_distribution.html` | the rank chart (queue `games/js/rank-distribution.min.js` on a page that includes it) |
| `core/includes/_search_box.html`, `_search_combobox.html` | the standard search input; a section's search box (combobox field, hints, listbox), with each site's rows in its `_search_options.html` |
| `core/includes/_tracking_button.html`, `_tracking_button_template.html` | the tracking dropdown and its clone twin |
| `core/includes/_status_filter.html`, `_mobile_filter_status.html` | the tracking status filter |
| `core/includes/_saved_filters_dropdown.html`, `_saved_filter_modals.html`, `_mobile_saved_filters.html` | saved filters, on both sites |
| `core/includes/_quick_mark_picker.html`, `core/js/quick-mark.js` | quick-mark mode |
| `core/js/filter-subcomponents.js`, `media-list-controls.js`, `media-search.js`, `media-tracking.js` | the Alpine components behind them |
| `core/services/titles.py`, `ranking.py` | the heading's wording; the chart's binning |

Rules:
- **Add a control to the shared template, not to one page.** The templates
  are the contract: each binds to an Alpine component exposing `filters`,
  `genres`, `initialized`, `debouncedFilterUpdate()`, `handleFilterChange()`,
  `updateSort()`, `toggleSortDirection()`, `viewMode` and `setViewMode()`
  (games: `filterComponent`; music: `mediaListControls`).
- Row and card styling is shared through CSS selector lists
  (`.game-row, .media-row { ... }`): one rule block, both families.
- Facet counts leave their own dimension out
  (`apply_album_filters(..., skip=("year",))`, `AlbumFilterEngine.facets()`),
  and both sides publish `year-counts-update` / `genre-counts-update`.
- **The year grid's fade is measured, not reasoned**: four generated boxes
  per tile, all fading `opacity`. Before touching it, read the file and look
  at real frames after a real click
  (`YearGridGapsFadeWithTheirTilesTests`).

### Music client-side filtering

Full text: `docs/agents/music-client-filtering.md`.

The album rankings page filters in the browser from `/api/all/`
(`sessionStorage`, keyed by the data version the page names). It is
progressive enhancement: the server-rendered page and its HTMX form work
without the bundle.

Rules, each pinned by `scripts/browser_smoke.js`:
- **Only `commit()` renders.** The engine and the form answer only the
  `change` that `mediaListControls.commit()` sends, which carries a `detail`.
- **htmx never answers Back on this page**: `music/home.html` replaces its
  `onpopstate`; the form saves no snapshots.
- **Taking over, the engine renders the form's filters if they differ from
  the ones the list was rendered with** (`#album-rendered-filters`, the
  server's echo, not the URL). With no engine to come, a failed request
  rolls the controls back onto that echo.
- **The jump box waits for the engine.**
- The engine's `change` listener has broken three times when given state:
  **keep any fix there stateless**, and pin it in the smoke test first.
- **The client-side suppressor cancels only GETs**: a row's toggle POST
  bubbles through the same listener.
- The payload's `nn`, `cn` and `ni` exist so the client never reimplements
  unidecode or a database collation: search and sort by them. Never fold
  the query for matching, on either side.
- A selected genre means itself and its descendants on both sides
  (`expand_genre_ids`, `_expandGenres`); a genre's count is a distinct count
  across its subtree.
- **Add a query to `core/tests/test_filter_parity.py` when adding a filter
  or a sort**, for music and games alike: it renders both sides on the same
  data and requires the same order.

### Album tracking

Full text: `docs/agents/album-tracking.md`.

`ListenedAlbum` / `WantToListenAlbum`, four exclusive states (Have, Heard,
Want, Untracked), with the vocabulary `?listened=own|yes|want|no` for
filtering and `?status=own|listened|want|none` for the toggle.

Rules:
- The button is one shared partial; a section's toggle route takes the
  item's pk as its one positional argument. Its dropdown is a menu
  (`role="menu"`), walked by a stateless key listener in
  `media-tracking.js`; an arrow does not open it in quick-mark mode or with
  Cmd, Ctrl or Alt held.
- **Every page that renders the button includes
  `music/includes/_album_tracking_script.html`** in its `pre_alpine` block.
- The toggle is atomic (one transaction under a per-user lock,
  `write_tracking_row`), and the cache is dropped after it commits.
- **Nothing per-user goes in `/api/all/`.** The page renders the id Sets per
  request.
- **Read a toggle's new status from the request, on `htmx:afterRequest`**:
  by `htmx:afterSwap` the target is the detached old element.
- Quick-mark: its click listener captures, ignores `event.detail >= 2`, and
  posts with the wrapper as source and target.
- Per-user cache keys are templates in `PER_USER_CACHE_KEY_TEMPLATES`,
  never in `CACHE_KEYS`.
- The Account modal says "tracked", not "heard", for Have and Heard
  together; the rank wording is `core.services.percentile`.
- The User admin's counts are correlated subqueries, not
  `Count("relation", distinct=True)`.

### Saved filters

Full text: `docs/agents/saved-filters.md`.

`SavedFilterSetBase`, three shared partials and a method contract
(`loadSavedFilters`, `applySavedFilter`, `saveCurrentFilters`,
`submitSaveFilter`, `renameSavedFilter`, `submitRenameFilter`,
`deleteSavedFilter`, `confirmDeleteFilter`, `hasActiveFilters`,
`savedFilters*`), which both `mediaListControls` and games'
`filterComponent` expose. Both sites render the shared partials.

Rules:
- **Applying a saved filter must not announce `genres-reset` or
  `year-reset`**: the mobile sheet shares the page's Alpine state at every
  width and answers by clearing.
- Music's write views are behind CSRF: test with
  `Client(enforce_csrf_checks=True)`.
- Deliberately uncached. `applySavedFilter` restores `sortDirection`, on
  both sites, pinned in source and minified form.

### Template Architecture

Django templates, server-rendered. Production uses the cached loader,
development the non-cached ones. `core/template_loaders.py` strips each
`.html` line's leading whitespace at load: **do not add markup whose meaning
depends on indentation** (`white-space: pre`, indented text in `<code>`)
without exempting it there.

## Application Structure (Django + HTMX + Alpine.js)

Full text, with every route, the styling rules' numbers, navigation, access,
the HTMX history rules, analytics and the dual-rendering table:
`docs/agents/application.md`.

**Styling.** Tailwind CSS v4 with DaisyUI v5; `lofi` (light) and `forest`
(dark). Custom components are in `theme/static_src/src/styles.css`.
- Text a reader needs is at least `text-base-content/65`.
- **In the dark theme, text is the accent, never the primary**: a component
  that `@apply`s `text-primary` needs its selector added under
  `[data-theme="forest"]` (`core/tests/test_theme_contrast.py`).
- **A control's spoken name holds its visible text** (WCAG 2.5.3):
  `aria-label="SNES: filter by Super NES"`. A parenthesis in a name is not
  matched ("Music, Beta").
- **A colour in a style is one of DaisyUI 5's `--color-*` variables**, mixed
  with `color-mix(in oklab, ... N%, transparent)` for an alpha. DaisyUI 4's
  names (`--bc`, `--b1`, `--p`) are defined nowhere and a declaration that
  reads one is dropped silently (`core/tests/test_theme_variables.py`).
- The year grid's tiles have their own heat colour, `--color-heatmap-tile`;
  the rank chart keeps `--color-heatmap`.

**Routes.** Games on `games.acclaimedmedia.org`: `/`, `/game/<slug>/`,
`/game/<igdb_id>/toggle-played/`, `/games/browse/`, `/games/<decade>s/`,
`/games/<year>/`, `/games/<slug>/` (SEO landing pages), `/download/`,
`/developers/`, `/developers/<slug>/`, `/lists/`, `/blog/`, `/import/`
(staff). Music on `music.acclaimedmedia.org`: `/`, `/<slug>/`, `/artists/`,
`/artists/<slug>/`, `/lists/`, `/download/`, `/import/` (staff),
`/<album_id>/toggle-listened/`, `/cover/...`, `/genres/<slug>/`,
`/<decade>s/`, `/browse/`, `/api/...`. Books on the games host, staff-only.
- **Album detail is the catch-all `/<slug>/`**: every fixed first segment on
  the music host is in `music.config.RESERVED_ALBUM_SLUGS`. A test fails if
  a route is added without reserving its segment.
- No script spells a music path: build links from `window.albumRankingsUrl`.
- A games batch import is all or nothing, through one loop
  (`import_handler._run_batch`). An exception's text goes to the log, never
  the page; an `ImportFileError` is written to be read. The three progress
  streams share `games/services/progress_stream.py`. The streams
  `EventSource` opens start work on a GET, so they answer only a
  same-origin request.
- Each entity list's sort starts in its own direction (`ASCENDING_SORTS`).
- Music is a beta while `music.config.MUSIC_BETA` is on. Staff pages are
  linked from nowhere.

**HTMX history** (`HTMXPushURLMiddleware` sets `HX-Push-URL` on every htmx
response but a Load More page):
- **htmx keeps no snapshots** (`historyCacheSize: 0`).
- **A page never pushes an entry of its own beside htmx's.** One that wants
  a tidier address rewrites htmx's entry in place with
  `history.replaceState`.
- Each view on `HTMXPartialMixin` sends `Vary: HX-Request`.
- Entity pages share one Load More, `core/js/entity-load-more.js`.

**Analytics.** gtag.js loads on the first interaction; an HTMX swap is a
page view only if the address changed.

**Client and server rendering must agree.** The rankings rows are rendered
by the Django templates and cloned from `<template>` elements by the
renderers (`game-list-renderer.js`, `album-list-renderer.js`,
`base-renderer.js`), filling `data-slot`s.
- When changing a row or card, change the template and the renderer, and
  keep `PLATFORM_FAMILIES` / `FAMILY_INFO` equal in Python and JS.
- **A slot must not sit inside `{% if item.something %}`**: a `<template>`
  is rendered with no item, and the slot vanishes from the clone.
- Grid cards are client-only. Verify both a fresh load and a filtered list.

## IGDB Integration

Full text for this section and the next: `docs/agents/igdb-and-hltb.md`.
For command usage, run `/igdb`.

- A single game's lookup answers `None` for a failure of ours or IGDB's and
  raises `GameNotFound` for an id IGDB has dropped. Every request carries
  `igdb.REQUEST_TIMEOUT`.
- A game page's description is IGDB's summary (`IGDBGameData.summary`,
  `seo.meta_description`); a description staff wrote on the `Game` comes
  first. `needing_igdb()` does not count a missing summary.

## HowLongToBeat playtimes

- **Open-ended games show no playtime.** `games/services/playtime.py` is the
  one place that applies `HLTBGameData.is_open_ended`: go through it for any
  new use of a playtime.
- The staff call is `open_ended_override` on the HLTB record, made in the
  admin. **Never `.update()` the override or `game_type` without
  re-saving**, which re-derives the flag.
- Which HLTB entry a game gets is `games/services/hltb_matching.py`, for the
  command and the weekly job alike.
- `refresh_all_metadata` fails (`CommandError`) when a phase could not run
  at all; errors on some games do not fail it. It moves the data version
  only if it changed what the pages show.

## Forum (removed)

The community forum (django-machina) was removed on 2026-10-17. Migration
`0115_drop_machina_tables` dropped everything of it.
`Publication.reputation_score` survives as display-only editorial metadata.

## Music Data Import

Full text, including the post-import metadata fetch and artist name
variants: `docs/agents/music-import.md`.

Four TSV files (`ArtistInfo.txt`, `ListData.txt`, `WebRankings.txt`,
`ListPositions.txt`; the current release is in
`acclaimedgames/test_input_files/music/`), imported in one transaction,
artists first: `python manage.py import_music_data [--dry-run]`.

Rules:
- **Artists and albums are upserted, not replaced**: artists by the
  provider's permanent `source_id`, albums by Wikidata id and then by
  `models.release_identity`. A kept album keeps its pk, slug, metadata,
  covers and tracking rows.
- **Artist slugs are not kept**: they follow the current names
  (`music.services.artist_slugs`), and a slug an artist loses redirects
  through `ArtistSlugHistory`. The admin cannot edit them.
- An album belongs to exactly the artists it credits (`AlbumCredit`); the
  credit line shows the credited name and links to the artist; `VA` is the
  last credit. The separators are `credit_separator` on both sides.
- The list type (All Time, Decade, EOY, Misc) is validated.
- **An import starts its metadata fetch** (`music/services/post_import.py`,
  `games/services/post_import.py`): in the foreground from a command, on a
  background thread from a staff page. One fetch per section at a time,
  under a `cache.add` lock with a heartbeat; **every metadata pass but a
  manual command's takes that lock** (`post_import.hold`, `run_weekly`).
  `METADATA_AFTER_IMPORT` turns it off, and it is off under test.
- **A cache error does not fail a committed import**: it is a warning that
  names `clear_music_caches`.
- An import re-adopts tracking rows (`reconnect_tracking_records`).

## Music Metadata Pipeline

Full text, including the Discogs API terms: `docs/agents/music-metadata.md`.

`fetch_album_metadata` runs four passes (Wikidata, cover art, Discogs,
MusicBrainz), then the genre rebuild, release dates, slugs and cache drop.
It runs weekly on Heroku Scheduler (`--weekly --with-musicbrainz
--refresh-stale 125`) and fails when the Wikidata pass lands nothing.

Rules:
- **Each pass keeps an album's failure to that album**, in a savepoint
  (`_for_one_album`), and **makes the album's requests before the savepoint
  opens**: network in `fetch`, which never writes; writes in the step,
  which reads the rows again.
- **Genres are our own vocabulary** (`music/services/genre_normalizer.py`),
  voted on by three sources and rebuilt offline, corpus-wide
  (`rebuild_album_genres`). An unclassified label creates nothing.
  Classifying a label is not free: read the per-album diff from
  `rebuild_album_genres --dry-run --report`.
- The genre tree stays two levels and single-parent; hybrids tag extra
  roots on the album (`HYBRID_ROOTS`).
- **Cover art is downloaded, not hotlinked** (`AlbumCover`,
  `AlbumCoverView`), kept only as an image under 5 MB. A `front` flag is not
  a sleeve: `musicbrainz.cover_quality` ranks them.
- **Discogs' terms ask for two notices**, both rendered and pinned by
  `music/tests/test_discogs_attribution.py`: the non-affiliation notice on
  every music page, and "Data provided by Discogs" beside the data, linked,
  never `rel="nofollow"`. We use no Restricted Data.

## Music and games query budgets

Full text and the numbers: `docs/agents/query-budgets.md`.

- **Answer a genre hierarchy from one query**:
  `core/services/genre_tree.py` (`descendants_by_id`), built once per
  request and passed in (`descendants=`). Nothing on a hot path walks
  `children`. Deliberately uncached, in both sections.
- **`with_list_count()` is a subquery a row**, never
  `Count("lists", distinct=True)`.
- **A many-to-many filter is an `EXISTS`, not a join**
  (`query_filters._related_to_any`): a join needs a `DISTINCT` over every
  column.
- **The games filters are one function**,
  `games.services.game_filters.apply_game_filters(qs, params, skip=...)`,
  as `apply_album_filters` is for albums: the list, the facet counts, the
  CSV and the landing pages all use it. `?platforms=` is platform ids and
  nothing else, as `?genres=` and `?series=` are ids.
  `query_filters.resolve_year_range` is the one rule for years.
- Budgets are pinned by count (`MusicQueryBudgetTests`,
  `GamesHomeGenreQueryBudgetTests`) and by growth
  (`games/tests/test_query_budgets.py`): add a page there when adding one.

## The rankings heading and the tab title

Full text: `docs/agents/headings-and-titles.md`.

- A filtered page's tab lists its facets and names its section; an
  unfiltered or landing page's reuses the heading. The client titles each
  state as a reload of its URL would (`scripts/browser_smoke.js` compares).
- A genre clicked in a music row announces `genres-selected`, which the
  filter component listens for: the heading and the tree are built from
  `filters`.
- There are no `?v=N` cache-busters: manifest storage hashes every static
  name.

## Domain

Full text, with DNS and the account flows: `docs/agents/domain.md`.

Three sites, one app: `acclaimedmedia.org` (landing, `urls_root.py`),
`games.acclaimedmedia.org` (`urls_games.py`, also `ROOT_URLCONF`),
`music.acclaimedmedia.org` (`urls_music.py`). One name for all of it:
**Acclaimed Media**.

Rules:
- **`core/sites.py` is the routing.** A link within a site is a plain
  `{% url %}`; a link to another site is `{% site_url 'music' 'music:home' %}`
  or `sites.site_url()`; a model or command that builds a URL uses
  `sites.site_reverse()`.
- Canonical links, sitemap `<loc>`s and structured data use
  `settings.SITE_ORIGINS` (`{{ canonical_origin }}`,
  `sites.canonical_url()`).
- The shared routes are in every URLconf (`urls_common.py`). The old apex
  paths redirect (`core.views.redirect_to_site`).
- **A POST unsubscribes; the link only asks.** The view is `csrf_exempt`:
  the token in the address is the credential.
- **Sign-up is the modal's, and the username rules are one function**
  (`User.username_error`), which the forms and
  `ModalAccountAdapter.populate_username` share.
- **A verification belongs to the account that asked for it**: the
  confirmation link logs in only the browser that signed up.
- Changing an account's email in the admin puts allauth's rows in step
  (`account_email.sync_address_rows`); `repair_email_rows` is for accounts
  changed before that.
- The session and CSRF cookies are `am_sessionid` and `am_csrftoken`, set on
  `.acclaimedmedia.org`. JavaScript reads the token through
  `readCsrfToken()`.
- **The three hosts must not be proxied by Cloudflare**: `get_client_ip`
  takes the last `X-Forwarded-For` entry, Heroku's router's.
- HTTPS is read from `X-Forwarded-Proto`. `localhost` and `127.0.0.1` are
  allowed hosts under `DEBUG` alone.

## Caching

Full text: `docs/agents/caching.md`.

Three aliases (`core/cache_config.py`): `default`, shared across processes
(a Postgres table in production); `local`, per-process, holding whole
rendered pages, deflated; `ratelimit`, per-process, the per-IP counters.

Rules:
- **There is no site-wide cache middleware, deliberately.** Whole pages are
  cached for anonymous visitors by `AnonymousResponseCacheMixin`, which
  swaps the CSRF token and the CSP nonce for sentinels on the way in and
  mints fresh ones on the way out. **A third per-request token would need a
  third pair.**
- **A whole-page cache key carries the host**, spelt one way
  (`sites.host_key`), never `get_host()`.
- **A cached page carries its data version** and is served only while it is
  current (`get_page_cache_version`), on both sites.
- **Every music cache write goes through `caching.cached` or
  `set_if_current`**; games' invalidated caches use the same generation
  guard, a family at a time (`games/cache.py`), and drop through
  `core.cache_helpers.drop_on_commit`, not `cache.delete`.
- **Add a music cached value to `CACHE_KEYS`** in `music/config.py`, or it
  will not be invalidated. Per-user keys are templates, not entries.
- **Every per-IP limit keys on
  `core.services.client_ip.get_client_ip`.**
- Games' `highlight` is the browser's alone: nothing of the visitor is
  rendered into a page that is kept. A games import drops the day-long
  caches a release changes (`games.cache.release_cache_keys`).
- `HEAD` is the `GET` it is served by. A request that claims to be a
  script's without the header is counted against the render budget, which
  only reports until `ANON_RENDER_BUDGET_ENFORCE` is set.
- A test of what a signal invalidates takes
  `core.tests.utils.CommitHooksRunNowMixin`.

## Content Security Policy

Full text: `docs/agents/csp.md`.

`SECURE_CSP_REPORT_ONLY`: it reports and blocks nothing yet.

Rules (`core/tests/test_csp.py`):
- **Every inline `<script>` carries `nonce="{{ csp_nonce }}"`.**
- **No inline event handlers.** A click behaviour is a data attribute and a
  delegated listener (`[data-href]`, `[data-close-dialog]`,
  `[data-confirm]`), not `onclick`. The one exception is
  `onclick="event.stopPropagation()"` on the tracking buttons.
- **A value in an Alpine expression is code, not text.** Validate it in the
  view against the values the page knows, and write it with `|escapejs`.
- **A CSV cell is text, never a formula.** Every CSV is written through
  `core.services.spreadsheet.SafeWriter`, the commands' reports included.
- `tojson` is marked safe, so it escapes; build JSON-LD with `seo.json_ld`.
- A FlatPage body cannot carry a nonce: no inline script, no third-party
  widget. No script comes from another origin but Google's tag and
  Cloudinary's upload widget; libraries are vendored
  (`games/static/games/js/vendor/README.md`).

## Production memory budget

Full text, with every measurement: `docs/agents/memory-budget.md`.

The web dyno has **512 MB for every gunicorn worker together**; a worker
plateaus near 200 MB. The `Procfile` follows from that: `--workers 2`,
`gthread` with `--threads 3`, no `--preload`, `--timeout 600` (the import's
SSE stream), `--max-requests 2000`.

Rules:
- **Anything that grows the rendered page, the boot imports or a
  per-process cache spends from that 512 MB twice over.** Raise `--threads`
  only against `memory.rss.bytes.max` measured on the dyno.
- The rankings page ships no server-rendered grid cards, one status menu per
  page (games), and platform and genre spans with `data-add-*` attributes,
  not handlers. Jump to rank renders a window; positions are absolute, so
  subtract `windowStart`.
- Alpine skips the filter UI the visitor cannot see: the sidebar div
  (`#desktop-filter-sidebar`, `#album-filter-sidebar`) must carry no
  directives of its own.
- A filter change leads (`debounceLeading`) only once the client engine is
  ready, and runs through `afterNextPaint`. Sidebar bindings read index
  maps, not `find()` over reactive arrays. `_writeHistory` is the one place
  a URL is written.
- A Load More or server jump fetches from the list's own address
  (`data-list-url`), not from the URL; a response without `#load-more-meta`
  is a failed page.
- Do not touch `_rollBackIfStranded` without reading the file: it has cost
  the most review rounds.
- Measure filter speed with real clicks, at 1x and 4x.

## Configuration

Full text, with every environment variable: `docs/agents/configuration-and-tests.md`.
`.env.example` lists the variables.

- Settings reads `.env`, which the shell beats, then
  `.env.development.local`, which beats both: **point a command at another
  database through a settings module, not `DATABASE_URL=...`**.
- A dyno with no `CACHE_URL` does not start.
- `SENTRY_ENVIRONMENT` is `production` on a dyno and `development`
  elsewhere, which sends nothing. `core.sentry.event_scrubber` adds
  allauth's password fields and the CSRF token to the denylist.
- `.coveragerc` omits migrations and the tests, and nothing else: **a new
  file is under the 100% gate from its first commit.**

**Two test runners, on purpose.** `pytest` is the gate (100% coverage, on
every commit); `scripts/run_tests.sh` runs the same suites under
`manage.py test`, where conftest's cache clearing does not apply. Run it
when a change touches caching, sessions or other process-wide state:
`venv/bin/pre-commit run django-tests --hook-stage manual`. Keep hooks in
`.pre-commit-config.yaml`, never in `.git/hooks`.

- **Tests cannot reach the network under pytest**, and run without outside
  credentials. Patch the client where the code under test reads it.
- Test mode is the `test` subcommand or pytest (`core.csp.running_tests`).
- **Tests pick a site the way a request does**: a module of music tests
  imports `from music.tests.site import setUpModule, tearDownModule`; a
  test that crosses sites uses `core.tests.utils.get_on_site`.
- A test that needs two timestamps in order sets them, a day apart; it does
  not sleep.
- **`soup.select()` does not look inside a `<template>`** (soupsieve 4, as a
  browser's `querySelectorAll`): a test of an Alpine `x-for` or `x-if` body
  or of a clone row uses `core.tests.utils.select_all`, or its
  `assertFalse` passes whatever the template holds.
- Import threads escape the test transaction on Postgres: tests that reach
  one run it inline (`InlineImportThreadMixin`). Do not assume a primary
  key of 1.

## Database

- **Development**: SQLite (`db.sqlite3`). **Production**: PostgreSQL 18 on
  Heroku. Set `TEST_DATABASE_URL` to run the suites on Postgres locally.
- The `rank` field on Game determines primary ordering (lower is better).

## Dependencies

Full text, with the worktree setup, the cloud session and CI's jobs:
`docs/agents/dependencies.md`.

- **Edit the `.in` files, never the `.txt` locks**, and recompile the dev
  lock after the production one:
  `pip-compile requirements.in && pip-compile requirements-dev.in`.
- `venv` at the root and `theme/static_src/node_modules` are symlinks into
  the main checkout in every worktree (`scripts/setup_worktree.sh`):
  replace the symlink with a real install before changing either on a
  branch. Use Homebrew's Python.
- CI (`.github/workflows/ci.yml`): `lint`, `pytest`, `django-tests`
  (Postgres 18), `production-install`, `audit`, `css`, `js`, `browser`.
  Heroku runs only the Python buildpack, so the committed
  `theme/static/css/dist/styles.css` and `.min.js` files are what ship: the
  `css` and `js` jobs fail if they differ from a rebuild. Node is pinned
  (`NODE_VERSION`).
- A Dependabot PR is a merge to `main` like any other: CI green, and a
  major only after reading its changelog.
- To run the smoke test locally, start `runserver` without the debug
  toolbar.

## Static Files

Full text: `docs/agents/static-files.md`.

- **CSS.** `python manage.py tailwind start` to watch,
  `python manage.py tailwind build` to build. **The build reads class names
  from every `.html`, `.py` and `.js` file, tests included**: rebuild after
  any change that names a class, and do not spell out one the pages do not
  use.
- **Icons.** MDI is a self-hosted subset: `./scripts/build_mdi_subset.sh`
  after adding one (`/icons`). `core/tests/test_icons_defined.py` fails on a
  class no mapping defines.
- **JavaScript.** **Always edit the source `.js`, never the `.min.js`**,
  then run `/minify` or `./scripts/minify_js.sh`. Two bundles (games,
  music), each starting with `core/static/core/js/base-renderer.min.js`.
  The pages load only the minified copies: pin a behaviour in both.
- `utils-base.js` loads on every page. **Go through its helpers**: stored
  preferences through `readStoredPreference` / `readStoredJson` /
  `storePreference` / `removeStoredPreference`, never bare `localStorage`;
  a scripted scroll asks `scrollBehavior()`; `fetchHtml` throws on an error
  status; a count the server swaps in is said through `announce()`; a POST
  reads the token through `readCsrfToken()`; desktop width is
  `isDesktopWidth()`; a replaced button keeps focus through
  `replaceKeepingFocus`; a search box aborts the request it overtakes.
- A search box is a combobox (`searchComboboxState`,
  `core/includes/_search_combobox.html`).
- `_escapeHtml` escapes as Django's `escape` does. A mobile row card's title
  is a link.

## Design Guidelines

### Quantitative Display Ruleset

When making any changes that affect **visual displays of quantitative information** (charts, graphs, tables with numbers, rankings, statistics, data visualizations), read and follow the principles in:

**`acclaimedgames/rulesets/Unified Quantitative Display Ruleset.md`**

Key principles: graphical integrity (what is shown must match the data),
data-ink ratio, comparison support, context (units, time frames), and no
chartjunk.
