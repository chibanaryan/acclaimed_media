<!-- Part of the agent documentation. AGENTS.md keeps each section's rules
     and points here for the reasoning, history and measurements behind
     them. Moved out of AGENTS.md, word for word, on 2026-11-12. -->

# Application Structure (Django + HTMX + Alpine.js)

The application uses Django templates with HTMX for dynamic interactions and Alpine.js for client-side reactivity.

### Views and Templates

- **games/** - Main Django app containing:
  - **views/** - Views for all routes, one module per page family
  - URL routing is `acclaimedgames/urls_games.py`, with the shared routes in `urls_common.py`
  - **templates/** - Django templates organized by feature:
    - **base.html** - Main template layout with navigation
    - **games/** - Game list, detail, and search templates
    - **developers/** - Developer list and detail templates
    - **lists/** - Lists and results templates
    - **articles/** - Blog templates
    - **pages/**, **flatpages/** - Static page templates
    - **auth/**, **account/** - The sign-in modal's partials, allauth's emails
  - **templatetags/** - Custom template filters (game_filters.py)
  - **middleware.py** - HTMXPushURLMiddleware for HTMX history support

### Application Features

**Styling:**
- Uses Tailwind CSS v4 with DaisyUI v5 component library
- Light theme (lofi) as default with forest dark theme available via theme switcher
- Responsive design using Tailwind's mobile-first breakpoints (md:, lg:, etc.)
- Custom components defined in `theme/static_src/src/styles.css` using Tailwind's `@layer components`
- Text a reader needs is at least `text-base-content/65`: `/50` was 3.2:1 on the light theme's `base-300`, and `/65` is 4.99:1 there, the worst case of both themes
- **In the dark theme, text is the accent, never the primary.** The dark theme's primary is a background colour, nearly as dark as its pages: as text it is 1.5:1 to 2.0:1. Its accent is the colour of text (links, each row's rank), at 65% lightness, 4.9:1 at worst; it was 50% and 2.7:1 to 3.6:1 until 2026-11-12. `styles.css` gives the accent to `text-primary`, `link-primary`, `hover:text-primary`, an outlined `badge-primary` and the mobile bar's active item under `[data-theme="forest"]`; a component that `@apply`s `text-primary` needs its selector added there, and `core/tests/test_theme_contrast.py` fails on one that is not. That test computes the ratios from the themes' OKLCH values, so change a colour there and run it
- **A control's spoken name holds its visible text** (WCAG 2.5.3): someone driving the page by voice says what they see. A platform's code on a row is `aria-label="SNES: filter by Super NES"`, not "Filter by Super NES". A parenthesis in a name is not matched: the mobile bar's Music link, which shows "Beta", is "Music, Beta"
- **A colour in a style is one of DaisyUI 5's `--color-*` variables** (`var(--color-base-content)`, mixed with `color-mix(in oklab, ... N%, transparent)` for an alpha). DaisyUI 4's names (`--bc`, `--b1`, `--p`, written `oklch(var(--bc) / 0.2)`) are defined nowhere, and a declaration that reads one is dropped silently: until 2026-11-12 thirty-six were, among them the staff import page's whole progress bar. `core/tests/test_theme_variables.py` fails on one
- **The year grid's tiles have their own heat colour**, `--color-heatmap-tile`: the label on a tile is the text colour, and on the dark theme's chart amber (`--color-heatmap`, which the rank chart keeps) it was 2.0:1 on the busiest year. `test_theme_contrast.py::YearGridLabelTests` says how light the tiles may go

**Template Filters:**
- `from_now` - Converts datetime to relative time (e.g., "2 hours ago")
- Custom utilities for formatting and string manipulation

**Routes**, on `games.acclaimedmedia.org` (`acclaimedgames/urls_games.py`):
- `/` - The game rankings, with filtering and search
- `/game/<slug>/` - Game detail view
- `/game/<igdb_id>/toggle-played/` - POST, the played / want-to-play toggle
- `/games/browse/` - Index of the landing pages
- `/games/<decade>s/`, `/games/<year>/`, `/games/<slug>/` - A decade's, a
  year's, a genre's or a platform's rankings (SEO landing pages)
- `/games/`, `/games/search/`, `/rankings/` - Redirects to `/`, query kept.
  The filter component still writes its address as `/games/?...`
- `/download/` - The rankings as filtered, as CSV
- `/developers/` - Developer list with game counts and hierarchy. Each sort
  starts in its own direction, as the other entity lists' do: a name A-Z, a
  rank from the top, a count biggest first (`ASCENDING_SORTS`; the page's
  `directionFor` agrees). Until 2026-11-10 every sort started at "asc" and
  the counts ran backwards to match, so "Asc" listed the most games first
- `/developers/<slug>/` - Developer detail view with subsidiary hierarchy and games
- `/developer-alias/<id>/` - 301s a developer's pk to its root developer's
  page, or answers 404 for a root IGDB gave no slug
- `/lists/` - The published source lists
- `/blog/` and `/blog/<slug>/` - Articles. `/news/` answers 410
- `/import/` - Staff import, and its three progress streams. A batch is all
  or nothing, streamed or not: until 2026-11-10 the streamed import went on
  to the next file after one failed and committed the rest, lists replaced
  with no games to match, or positions attached by rank to the previous
  release's games. Both run one loop, `import_handler._run_batch`, which
  owns the transaction, the error rule and the "Updated" stamp: a handler
  raises and says nothing itself, so a failed file is named once, and an
  exception's text goes to the log, never the page (an `ImportFileError`
  is written to be read, and is shown). They were two copies until
  2026-11-10 and had drifted three times. Each caller starts the metadata
  fetch itself. The three streams (IGDB, Wikipedia, the batch) share their
  queue and their loop, `games/services/progress_stream.py`, since
  2026-11-12: every one polls every 15 seconds and sends a keepalive, which
  the IGDB stream did not. "Load Test Data" is refused outside `DEBUG`. The two that
  `EventSource` opens start their work on a GET, so they answer only a
  request whose `Sec-Fetch-Site` is `same-origin` (or absent, for a browser
  too old to send it): a link followed from another site carries the
  session cookie
- `/page/<slug>/` and the other shared routes - see "Domain"

Book routes, on the games host (staff-only; `BOOKS_ENABLED` shows the links):
- `/books/` - Book list with filtering and search
- `/books/<slug>/` - Book detail view
- `/books/authors/` - Author list with book counts
- `/books/authors/<slug>/` - Author detail view with books
- `/books/import/`, `/books/toggle-read/<goodreads_id>/`, `/books/search/`

Music routes, on `music.acclaimedmedia.org` (they were under `/music/` at
the apex until 2026-10-30):
- `/` - Album rankings with HTMX search, year/artist/genre filters and sorting
- `/<slug>/` - Album detail with list appearances grouped by list type
- `/artists/` - Artist list with album counts
- `/artists/<slug>/` - Artist detail with ranked albums
- `/lists/` - The published source lists behind the rankings
- `/download/` - The rankings as filtered, as CSV
- `/import/` - Staff import for the four release files. Linked from nowhere,
  staff included: staff type the URL
- `/<album_id>/toggle-listened/` - POST, `?status=none|want|listened|own`,
  answering with the re-rendered button for HTMX to swap
- `/cover/<release_mbid>/<image_id>-<size>.jpg` - Cover art served from our own
  store, cached a year and immutable
- `/genres/<slug>/` - A root genre's rankings (SEO landing page)
- `/<decade>s/` - A decade's rankings (SEO landing page)
- `/browse/` - Index of the landing pages
- `/api/...` - the music API (`music-api:`), listed under "API Architecture"

Album detail is the catch-all `/<slug>/`, so every fixed first segment on the
music host - music's own routes and the shared ones (`accounts`, `admin`,
`api`, `page`, ...) - is in `music.config.RESERVED_ALBUM_SLUGS` (and a decade
shape in `RESERVED_ALBUM_SLUG_PATTERN`), which `Album._build_unique_slug`
treats as taken. A test walks `urls_music` and fails if a route is added
without reserving its segment.

**Music landing pages** are games' `/games/<genre>/` and `/games/<decade>s/`
for albums: `MusicLandingPageView` subclasses `AlbumHomePageView` and injects
the path's filters into `request.GET` - in `render_rankings()`, not `setup()`
as games does, so the cache batch covers the injection.
Root genres with a directly tagged album and at least `MIN_GENRE_ALBUMS`
across their subtree qualify, and decades with `MIN_DECADE_ALBUMS`; the
lists are cached under `CACHE_KEYS`. They are self-canonical, carry an
ItemList (`core.services.seo`), and are discovered through the sitemap
only - no nav, badge or footer link, as for games. No year pages: album
slugs such as `1999` already own those paths. The client pushes every
filter change onto `window.albumRankingsUrl` (`/?...` on the music host)
rather than the current path, and both popstate readers read a landing
page's bare path as `window.albumLandingSearch` - otherwise clearing the
genre on `/genres/rock/` pushed the rock URL back. The album renderer builds
every link from `window.albumRankingsUrl` too (`_musicPath`), so no script
spells a music path.

**Navigation:** the sidebar, top to bottom, is the site menu
(`core/includes/_site_menu.html`: "Acclaimed Media" over the current site's
name, opening in place to Games, Music and All sites, absolute links through
`{% site_url %}`; a `<details>`, so it needs no Alpine, and `base.html`
closes it on an outside click or Escape), the site's own links (`core/includes/_sidebar_nav.html`:
Rankings, Developers, Source Lists and Blog for games; Albums, Artists and
Source Lists for music), its search, and the shared bottom block - account,
Donate, About / FAQ, Contact, theme, socials. `media_type` comes from the
host (`games.context_processors.media_type`), so a shared page such as About
keeps the sidebar of the site it was opened on. Staff pages - both import
pages - are linked from nowhere. The games mobile bar has a Music icon and
music's a Games icon.

**Access:** music is public. Reads are open to everyone; the listen toggle
answers a signed-out visitor with games' login redirect and the saved-filter
API with games' 403; `/import/` is staff-only, behind
`core.mixins.StaffOnlyMixin`.

- Books still uses `core.mixins.StaffOnlyMixin` / `core.permissions.IsStaffOrHide`.
- Music is a beta, and says so everywhere while `music.config.MUSIC_BETA` is
  on: a notice with a feedback link at the top of every page on the music host
  (`music/includes/_beta_notice.html`, from `base.html`), and a "Beta" badge
  (`music/includes/_beta_badge.html`) on every music heading and on every
  way in - the site menu (on music, beside the site's own name), the games
  mobile bar's Music icon, and the landing page's Music card, which also
  says it in words. Turning `MUSIC_BETA` off removes them all.
- A renamed artist's old slug redirects. Every import and Wikidata pass
  rebuilds slugs from the current names (see "Music Data Import"), and both
  keep the slug an artist loses in `ArtistSlugHistory`
  (`artist_slugs.record_slug_changes`), which `ArtistDetailView` 301s to the
  current slug, query string kept. A slug an artist holds now is never kept
  there, so a live page always wins, and an artist the file drops takes its
  history with it. Only the page redirects: the API's artist detail is a
  404, and a `?artists=` filter on an old slug matches nothing. Until
  2026-11-02 nothing redirected, by decision at launch.

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

It sets `HX-Push-URL` on every htmx response but a Load More page, so htmx
pushes an entry for every request, whether or not the element asked. Two
rules follow, both since 2026-11-02 and both run by `scripts/browser_smoke.js`
("Back from a search on ..."):

- **htmx keeps no snapshots** (`historyCacheSize: 0, refreshOnHistoryMiss:
  true` in `base.html`'s `htmx-config`), so Back onto an htmx entry reloads it.
  A snapshot holds the DOM Alpine built, and restoring one threw an Alpine
  error per `x-for` clone on every entity page; with none stored, htmx fetched
  the entry as a partial and swapped it in for the whole body.
- **A page never pushes an entry of its own beside htmx's.** Each entity page
  (artists, source lists, developers) used to, so a search or a sort took two
  presses of Back, and the first reloaded nothing. One that wants a tidier
  address rewrites htmx's entry in place:
  `history.replaceState(history.state, '', url)`, on its `htmx:afterRequest`
  or after `htmx.ajax(...)` resolves, since htmx pushes before either.

Each view on `core.mixins.HTMXPartialMixin` sends `Vary: HX-Request`, as
the rankings pages do with `vary_on_headers`: one address answers with a
fragment or the page, and a browser's cache could otherwise hand back the
fragment on Back from another site.

The developers, games source-lists and authors pages share one Load More,
`core/js/entity-load-more.js`, configured by its button's data attributes
(`data-entity-load-more`, `data-list-url`, `data-append`, ...). It keeps
games' rules: it fetches from the list's own address, which the server
renders onto the button, not from the URL; a response without
`#load-more-meta` is a failed page; a page whose button a search has replaced
is dropped; and the button moves on before anything else can throw. Until
2026-11-03 each page had an inline copy that did none of this (smoke:
"Load More answered by another page", "Load More behind a search").

### Google Analytics Integration

Google Analytics 4, property `G-0591405Q89`, in `games/templates/base.html`.

- **gtag.js loads on the first interaction, not with the page**: the first
  `pointerdown`, `touchstart` or `keydown`, then in an idle moment
  (`initGA`, `loadGoogleAnalytics`). It keeps the script out of the first
  paint, and it means a visitor who never touches the page is not counted.
- **The page view is sent as it loads**, and remembered as
  `window.lastTrackedPagePath`.
- **An HTMX swap is a page view only if the address changed.** The
  `htmx:afterSwap` listener compares `pathname + search` with
  `lastTrackedPagePath`. Every swap used to count, so opening the sign-in
  modal or toggling a played button was a view of the page already open.
- A filter change the client engine answers sends no request and no swap,
  so it is not a page view; one the server answers is.

### Development Notes

- Template reloading works in development via Django's non-cached template loaders
- In production, template caching is enabled for performance

### Home Page Client/Server Rendering Consistency

The home page game rankings use a **dual-rendering architecture** that requires careful coordination:

**How It Works:**
1. **Server-side rendering**: Django templates render game rows with actual data on initial page load
2. **Client-side rendering**: JavaScript clones `<template>` elements and fills them with data for filtered/paginated results
3. **Single source of truth**: The same Django templates (`_game_row_desktop.html`, `_game_row_mobile.html`) serve both purposes
4. **Grid cards are client-only**: `_game_card_grid.html` is rendered solely into `#grid-card-template`; the server sends rows and the bundle builds the grid (see "Rankings page weight" under "Production memory budget")

**Template Structure:**
- When `game` context is provided → server renders with data
- When `game` is absent (inside `<template>` tags) → renders empty structure with `data-slot` attributes for JS

**Files That Must Stay In Sync:**

| Server-Side (Python/Django) | Client-Side (JavaScript) |
|----------------------------|--------------------------|
| `games/templates/games/includes/_game_row_desktop.html` | `games/static/games/js/game-list-renderer.js` |
| `games/templates/games/includes/_game_row_mobile.html` | (the same file: `_renderDesktopRow`, `_renderMobileRow`) |
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

The grid card's `srcset` is the one attribute the renderer derives rather
than reads: the payload carries only the 250px cover's URL, both shapes a
cover URL takes name the size the same way, and
`AlbumListRenderer.coverSrcset` writes the 500px one for 2x. The parity
test compares it with the server's for each shape.

**When Modifying Game Rows:**
1. Update the Django template for server-rendered output
2. Update the JavaScript renderer's DOM-cloning logic (uses `data-slot` attributes)
3. Ensure `PLATFORM_FAMILIES` and `FAMILY_INFO` constants match between Python and JS

There is no third copy to keep in step. Until 2026-11-12 the renderer also
built each row, the played button and the grid card from strings, for a page
with no `<template>`s, about 300 lines that could not run: the page that
loads the bundle always renders them. Without them the engine now declines to
start (`GameListRenderer.hasTemplates`), and the server goes on rendering.

**Key Data Slots:** `rank`, `global-rank`, `thumbnail`, `name`, `year`, `title-link`, `thumb-link`, `year-link`, `meta-row`, `platforms`, `genres`, `list-count`, `primary-developer`, `played-button`

**Testing:** After changes, verify both:
- Fresh page load (server-rendered)
- Filtered results (client-rendered via JS template cloning)

**An undated item** (2026-11-10): a game's year is no link, on either side
(it went to `?start=None&end=None` from the server and `?start=null` from
the renderer), and an album's `year` slot holds its own brackets, so the
row shows nothing where it showed "()". **The end of a list** reads "All N
results loaded" from both sides on both sites;
`music/tests/test_load_more_parity.py` renders music's note and button both
ways, where the engine used to remove the container.
