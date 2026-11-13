<!-- Part of the agent documentation. AGENTS.md keeps each section's rules
     and points here for the reasoning, history and measurements behind
     them. Moved out of AGENTS.md, word for word, on 2026-11-12. -->

# Backend Structure

- **acclaimedgames/** - Django project settings and main URL configuration
- **core/** - Shared infrastructure for multi-media support:
  - **sites.py**, **middleware.py** - The three sites by host, and the middleware that routes to their URLconfs (`acclaimedgames/urls_root.py`, `urls_games.py`, `urls_music.py`, with the shared routes in `urls_common.py`)
  - **views.py** - The landing page, the apex's redirects to the two sites, `healthz`
  - **models.py** - User model, abstract base classes (MediaItemBase, CreatorBase, ExternalDataBase, UserTrackingBase)
  - **mixins.py** - Shared view mixins (RobustPaginationMixin, HTMXPartialMixin)
  - **templatetags/core_filters.py** - Shared template filters
  - **templates/core/includes/** - Shared templates (`_base_media_row.html`, the ranking-page controls)
  - **static/core/js/** - Base JavaScript renderer classes
- **games/** - Main Django app containing:
  - **models.py** - Core data models (Game, Developer, Platform, List, etc.)
  - **api/** - REST API with views, serializers, and URL routing
  - **views/** - The views, one module per page family: `rankings` (home and
    the SEO landing pages), `game_pages` (detail and the played toggle),
    `developers`, `lists`, `download` (CSV), `content` (contact, flat pages,
    blog, 404, robots.txt), `imports` (staff), `auth` (the sign-in modal),
    plus `filter_titles` and `_helpers`. `__init__` re-exports every name,
    so `games.views.X` still resolves; patch a name where it is read
    (`games.views.rankings._get_year_bounds`). Split from one 4,000-line
    module on 2026-10-26
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
  - **management/commands/** - Book metadata commands (fetch_book_metadata.py)
  - **templates/books/** - Book templates

- **music/** - Music app for album rankings:
  - **models.py** - Album, Artist, MusicGenre, MusicPublication, MusicList, AlbumListMembership
  - **api/** - REST API with views, serializers, and URL routing (read-only but for saved filters, deliberately uncached)
  - **views.py** - Album/artist/source-list views and the SEO landing pages (the import page behind `core.mixins.StaffOnlyMixin`)
  - **sitemaps.py** - The music sitemap sections
  - **services/landing_pages.py** - Which genre and decade landing pages exist
  - **services/import_handler.py** - Imports the four-TSV album ranking release
  - **services/credits.py** - The credit line, and which albums are whose (from `AlbumCredit`)
  - **templatetags/music_filters.py** - Music-specific template filters
  - **management/commands/import_music_data.py** - Loads the ranking release files
  - **templates/music/** - Music templates; album rows extend `core/includes/_base_media_row.html`

**Installed Apps** (in `INSTALLED_APPS` order):
- `django.contrib.admin`, `auth`, `contenttypes`, `sessions`, `messages` - Django's own
- `whitenoise.runserver_nostatic` - WhiteNoise serves static files under `runserver` too
- `django.contrib.staticfiles` - Static file management
- `django.contrib.flatpages` - Flat pages framework for CMS content
- `django.contrib.sites` - Sites framework (the `Site` row; routing by host is `core/sites.py`)
- `django.contrib.postgres` - PostgreSQL-specific features
- `django.contrib.humanize` - `intcomma` and friends in templates
- `django.contrib.sitemaps` - The per-site `sitemap.xml`
- `django.forms` - Django's form widget templates, as an app. No
  `FORM_RENDERER` is set and no template overrides one, so it changes
  nothing today
- `corsheaders` - CORS support
- `rest_framework` - Django REST Framework
- `tailwind` - django-tailwind integration
- `theme` - Tailwind CSS theme app with DaisyUI
- `core` - Shared infrastructure (User model, abstract bases, mixins)
- `games` - Main game aggregation app with HTMX and Alpine.js
- `books` - Book rankings app (staff-only; `BOOKS_ENABLED` shows its nav links)
- `music` - Album rankings app
- `allauth`, `allauth.account`, `allauth.socialaccount` and its `google` and
  `facebook` providers - Sign-in
- `django_extensions` - `shell_plus`, `runserver_plus`
- `debug_toolbar` - Appended under `DEBUG` when it is installed, with its middleware

**Middleware:**
- `django.middleware.security.SecurityMiddleware` - Security headers
- `core.middleware.SiteHostMiddleware` - Picks the site (landing, games,
  music) and its URLconf from the host; see "Domain"
- `django.middleware.csp.ContentSecurityPolicyMiddleware` - The report-only
  policy and the nonce; see "Content Security Policy"
- `whitenoise.middleware.WhiteNoiseMiddleware` - Static file serving in production
- `games.middleware.UncompressedUptimeCheckMiddleware` - Answers a `GET`/`HEAD`
  of `/` from `SentryUptimeBot` that refuses gzip with a 2-byte 200, before
  rate limiting and sessions. Two SentryUptimeBot checks hit `/` every
  minute: ours (at :17, sending gzip) and one at :39 that sends no
  `Accept-Encoding` and pulled the whole ~667 KB page. Sentry Support
  confirmed on 2026-10-26 that the :39 check is not in our organization and
  is tracing it, so each :39 check temporarily logs its `sentry-trace` to
  `games.middleware.uptime`; remove that once they name the source. The
  2-byte answer proves only that a dyno is up - our gzip monitor, which
  still gets the real page, is the one that catches a broken render, so do
  not delete it
- `games.middleware.RateLimitMiddleware` - Per-IP rate limiting (see "Caching")
- `games.middleware.EventStreamAwareGZipMiddleware` - gzip for any client that
  accepts it, except `text/event-stream`, which zlib would buffer
- `django.contrib.sessions.middleware.SessionMiddleware` - Session management
- `corsheaders.middleware.CorsMiddleware` - CORS headers
- `django.middleware.common.CommonMiddleware` - Common utilities
- `django.middleware.csrf.CsrfViewMiddleware` - CSRF protection
- `django.contrib.auth.middleware.AuthenticationMiddleware` - Authentication
- `allauth.account.middleware.AccountMiddleware` - django-allauth's account state
- `django.contrib.messages.middleware.MessageMiddleware` - Messages
- `django.middleware.clickjacking.XFrameOptionsMiddleware` - Click-jacking protection
- `django.contrib.flatpages.middleware.FlatpageFallbackMiddleware` - Flat pages routing
- `games.middleware.HTMXPushURLMiddleware` - HTMX history/URL push support
