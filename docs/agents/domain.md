<!-- Part of the agent documentation. AGENTS.md keeps each section's rules
     and points here for the reasoning, history and measurements behind
     them. Moved out of AGENTS.md, word for word, on 2026-11-12. -->

# Domain

Three sites, one app, since 2026-10-30:

| Host | Site | URLconf |
|---|---|---|
| `acclaimedmedia.org` | the landing page: one card per site | `acclaimedgames/urls_root.py` |
| `games.acclaimedmedia.org` | the game rankings, at the paths the apex had | `acclaimedgames/urls_games.py` (also `ROOT_URLCONF`) |
| `music.acclaimedmedia.org` | the album rankings, at the root of the host | `acclaimedgames/urls_music.py` |

There is one name for all of it, **Acclaimed Media**: every title suffix,
`og:site_name`, the JSON-LD, the emails and `Site.name` (migration `0123`).
Neither site names itself. The favicons are still the old Acclaimed Video
Games artwork until a new one is drawn, and a page without artwork of its
own has no `og:image`: the old default was removed. Mail still goes to
and from `contact@acclaimedvideogames.com`, the address Titan and Brevo have
verified.

**`core/sites.py` is the routing.** `core.middleware.SiteHostMiddleware`
reads the host, records `request.site_key` (`"root"`, `"games"`, `"music"`)
and sets `request.urlconf`, which Django uses to resolve the path and as the
default for every `reverse()` and `{% url %}` during the request. So a link
within a site is a plain `{% url %}`; a link to *another* site needs that
site's URLconf and origin, which is `{% site_url 'music' 'music:home' %}`
(`core_filters`) or `sites.site_url()`. A model or a command that builds a
URL whatever the request is uses `sites.site_reverse()` (music's
`get_absolute_url` and cover URLs do). Any other host - the test client's
`testserver`, `127.0.0.1` - gets `ROOT_URLCONF`, the games site's.

- **Origins.** `settings.SITE_ORIGINS` holds the three public origins, used
  for canonical links, the sitemap `<loc>`s and structured data
  (`{{ canonical_origin }}` follows the host; `sites.canonical_url()`).
  `CANONICAL_ORIGIN` is the apex's, for emails and the fetchers'
  User-Agent. A cross-site *link* (`site_origin()`) keeps the request's
  scheme, and its port on localhost alone, so `games.localhost:8000` links
  to `music.localhost:8000`. Not a port on the public domain: the router
  passes on whatever a caller writes, and every link to another site was
  rendered with it (`https://music.acclaimedmedia.org:8443/`, until
  2026-11-09).
- **The shared routes** - sign-in, `accounts/`, the contact form,
  `/page/<slug>/` (About, Donate, Privacy, Legal), unsubscribe, admin,
  `healthz/`, `robots.txt`, `sitemap.xml` - are in every URLconf
  (`urls_common.py`), so a visitor uses them without leaving their site.
  The shared pages are one copy: their canonical link and sitemap entry are
  the apex's. At the apex they render without a sidebar.
- **The unsubscribe link asks; a POST unsubscribes** (2026-11-10). It
  unsubscribed on a GET, and a mail scanner that follows every link in a
  message (Outlook's Safe Links) did it for the reader. The page's button
  POSTs, and so does a mail client's own control, through the email's
  `List-Unsubscribe-Post` header (RFC 8058). That request has no cookie, so
  the view is `csrf_exempt`: the token in the address is the credential.
  The page says `noindex`, through `base.html`'s `robots` block, as the
  contact thank-you and the email confirmation do: its address carries the
  reader's token.
- **Sign-up is the modal's, and the username rules are one function**
  (2026-11-10). `User.username_error` (3 to 30 letters, digits, `_` or `-`,
  not a name a verified account holds) is used by the sign-up and profile
  forms and by `ModalAccountAdapter.populate_username`, which allauth's own
  forms reach without either. allauth's `/accounts/signup/` was still
  mounted and the adapter took any posted username: none of the rules, and
  a name equal to another person's email, which then held the name that
  person's signup defaults to. The page now redirects a signed-out visitor to
  `/#signup`, where `modal-handlers.js` opens the modal on its sign-up
  screen (once htmx has started, never for a signed-in visitor, whom
  `#authModal[data-signed-in]` names, and closing the dialog again if the
  form's request fails), and a signed-in one home (its route name
  stays, since allauth's flows reverse it, and its login page links to it),
  a name that breaks the rules
  gives way to the email, and an email someone already holds as a username
  gets allauth's generated name where it was an `IntegrityError`, as does
  one longer than the column's 150 characters, which was a `DataError` on
  Postgres until 2026-11-12.
- **A verification belongs to the account that asked for it** (2026-11-11).
  The modal remembers the account it showed "verification sent" or "Email
  Not Verified" for, in the session (`auth.PENDING_ACCOUNT_KEY`), where
  the password was just given. The confirmation link logs in only that
  browser; anyone else who opens it (a mail scanner, the owner of an
  address someone else signed up with) gets the address verified and a
  Log In button. Any login, refused or not, replaces what an earlier
  screen in that browser remembered. Resend sends for that account, never
  the address posted, and says so when another account has verified the
  address, or it is verified already; signing up on an address another
  account waits on points to logging in or a reset. An account with no
  address row for its email is pointed to the contact form: the resend
  does not repair the rows, which is the admin save's to do.
- **Changing an account's email in the admin puts allauth's rows in
  step** (2026-11-12, `core.services.account_email.sync_address_rows`,
  from `UserAdmin.save_related`, after the inline's formset has saved).
  The admin wrote `User.email` and left the `EmailAddress` rows: the old
  row stayed, often primary and verified, and allauth's password reset
  and its own login read those rows first, so whoever held the old
  address could still reset the password. Now the account is left the
  rows a sign-up on the new address would have: one, lower-case, primary,
  verified only if the account had verified that address already. The
  form refuses an address another account has verified, staff are told
  what went, and no email is sent (the reader confirms it from the login
  screen's Resend). Only a changed email is checked or synced: a
  secondary address a reader added themselves is kept, and an account
  changed before this keeps its old rows until its email is next changed,
  or until `python manage.py repair_email_rows --sync <username>` is run
  for it: without `--sync` the command lists such accounts and changes
  nothing (ROADMAP).
- **The old apex paths redirect.** Everything the apex served before is in
  links and search indexes, so `urls_root`'s catch-all
  (`core.views.redirect_to_site`) sends `/music/<rest>` to
  `music.…/<rest>`, `/api/music/<rest>` to `music.…/api/<rest>`, and every
  other path to the same path on `games.`, query string kept. `/` with a
  query is an old filter link, since the rankings lived there, and goes to
  `games.` too, if it carries one of the rankings' own parameters
(`OLD_FILTER_PARAMS`); anything else, such as a tracking tag, stays on the
landing page and shares its cache.
- **Each site has its own `robots.txt` and `sitemap.xml`**
  (`core.sitemaps.for_site` puts each `<loc>` on the site's origin; the
  `Site` row's domain stays the apex).
- **One sign-in for all three.** In production the session and CSRF cookies
  are set on `.acclaimedmedia.org`, and both were renamed (`am_sessionid`,
  `am_csrftoken`) with the move, since a host-only cookie of the old name
  left on the apex would otherwise be sent beside the new one. Everyone was
  signed out once. JavaScript that reads the CSRF cookie reads
  `am_csrftoken`. The theme choice is in `localStorage`, which is per
  origin, so `_theme_script.html` also keeps it in a domain-wide `theme`
  cookie, which wins. It asks for the domain's and writes the host's own
  if the browser did not keep it, as it does not on a host with no parent
  a cookie may name (`*.localhost`, an address such as `127.0.0.1`). Until
  2026-11-12 nothing was written there, so a `theme` cookie already on
  `127.0.0.1` could not be changed and put the reader back on its theme at
  every page (`core/tests/test_theme_cookie_js.py`; smoke: "a theme chosen
  on 127.0.0.1 stays").
- **Development** uses the same names under localhost: `localhost:8000`,
  `games.localhost:8000`, `music.localhost:8000` (Chrome resolves
  `*.localhost` itself; `ALLOWED_HOSTS` takes `.localhost`, `localhost` and
  `127.0.0.1` under `DEBUG` alone since 2026-11-12, and production's list
  is its three hosts).
  The cookies are host-only there, so signing in on one does not sign you
  in on the others.

DNS is in Cloudflare (James's account; both zones), and the app on Heroku
has three custom domains, each with Heroku's ACM certificate:

- **`acclaimedmedia.org`, `games.` and `music.` are DNS-only** (grey cloud),
  CNAMEs to their Heroku DNS targets. They must not be proxied:
  `get_client_ip` takes the last `X-Forwarded-For` entry, Heroku's router's,
  and behind Cloudflare that would be a Cloudflare address, so every visitor
  would share a rate-limit bucket.
- **HTTPS is read from `X-Forwarded-Proto`** (`SECURE_PROXY_SSL_HEADER`),
  which Heroku's router sets on every request. It used to work only because
  the buildpack tells gunicorn to trust forwarded headers; CI's
  `production-install` job checks the redirect both ways.
- **Every other host is a 301 at Cloudflare's edge**: `www.acclaimedmedia.org`
  to the apex, and `acclaimedvideogames.com` and `www.acclaimedvideogames.com`
  to `games.acclaimedmedia.org`, path and query string kept. They are
  proxied records with a placeholder address (`192.0.2.1`) and a dynamic
  redirect rule in their zone, and never reach a dyno.
- Keep the old domain registered, and leave its MX, SPF, DKIM and DMARC
  records alone: the contact address still lives there.
- Sentry's uptime monitor should fetch `https://games.acclaimedmedia.org/`:
  the apex is now a light page that does not exercise the rankings render.
