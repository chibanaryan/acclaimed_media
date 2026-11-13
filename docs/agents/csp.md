<!-- Part of the agent documentation. AGENTS.md keeps each section's rules
     and points here for the reasoning, history and measurements behind
     them. Moved out of AGENTS.md, word for word, on 2026-11-12. -->

# Content Security Policy

`SECURE_CSP_REPORT_ONLY` in settings, with Django's own
`ContentSecurityPolicyMiddleware` and `{{ csp_nonce }}`, since 2026-10-26.
It reports and blocks nothing; enforcing it means moving the dict to
`SECURE_CSP` once Sentry's CSP reports are quiet. What it rests on:
- Every inline `<script>` carries `nonce="{{ csp_nonce }}"`. Scripts an
  htmx swap brings in get the page's nonce through the `htmx-config` meta
  tag's `inlineScriptNonce`. Cached pages are given the request's nonce, as
  above.
- There are no inline event handlers, which a nonce forbids. Mobile row
  cards navigate through `[data-href]`, dialogs close through
  `[data-close-dialog]`, and the import page's confirms through
  `[data-confirm]`, each with delegated listeners. A card answers as a link
  would: Ctrl, Cmd, Shift or the middle button (`auxclick`) opens a new tab. The one exception is
  `onclick="event.stopPropagation()"` on the tracking buttons, on rows that
  carry no Alpine on purpose; `'unsafe-hashes'` with its hash
  (`core.csp.handler_hash`) allows exactly that text.
- `'unsafe-eval'`, because Alpine evaluates expressions with `new Function`.
  Dropping it needs Alpine's CSP build.
- `style-src` has `'unsafe-inline'` and no nonce: a nonce would disable it,
  and `style=""` attributes are everywhere.
- `img-src` also takes `http://*.localhost:*` under `DEBUG`, where the sites
  are separate plain-http origins and the landing page's covers cross them.
- No script comes from another origin but Google's tag and Cloudinary's
  upload widget (the admin's). The admin's markdown preview fetched
  `marked` from a CDN, unpinned, until 2026-11-12; it is vendored
  (`games/static/games/js/vendor/`, whose README lists every vendored
  library and its version).
- Reports go to Sentry's security endpoint, built from the DSN
  (`core.csp.sentry_report_uri`). Under test and on a developer's machine
  there is none (`SENTRY_ENABLED`).
- A `meta-webindexer` report naming an `acclaimedvideogames.com` host does
  not count against "quiet". Meta's crawler re-renders pages it stored before
  the domain move (from 2026-10-30): their assets 301 to
  `acclaimedmedia.org`, which the stored page's `'self'` does not cover, and
  the report names the old URL. The policy is stored with the page, so no
  change to ours reaches it. No template or asset references the old host,
  though some posts link to it. A real browser's report still counts.
- A FlatPage body cannot carry a nonce, so it cannot hold an inline script,
  and a third-party widget in one means widening the policy for the whole
  site. The Donate page's Ko-fi button was Ko-fi's script until 2026-10-30
  and is now a plain link. Its PayPal buttons are forms, hence
  `form-action https://www.paypal.com/donate`.

`core/tests/test_csp.py` pins the nonces and the handler rule. When adding
an inline script, give it the nonce; when adding a click behaviour, use a
data attribute and a delegated listener, not `onclick`.

**A value in an Alpine expression is code, not text.** `x-data="{ sort:
'{{ sort }}' }"` is autoescaped to `&#x27;`, which the attribute decodes back
to a quote before Alpine evaluates it, so a request value there is script
injection. Validate it in the view against the values the page knows, and
write it with `|escapejs`. Until 2026-11-03 `?dir=` and `?sort=` reached four
pages' expressions unchecked (`SortParametersStayDataTests`).

**A CSV cell is text, never a formula.** Both downloads write through
`core.services.spreadsheet.SafeWriter`, which prefixes a cell starting
`=`, `+`, `-` or `@` with an apostrophe: names come from the release files,
IGDB and Wikidata, and Ed Sheeran's "+" and "=" are real albums.

**`tojson` is marked safe, so it escapes.** It writes `<`, `>`, `&` and `'`
as their JSON escapes, as Django's `json_script` does: its output goes into
`<script type="application/json">` bodies and one single-quoted attribute
(`data-bins`). Bare `json.dumps` was safe only while every caller passed
numbers.
