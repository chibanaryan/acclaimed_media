# Vendored browser libraries

Copied into the repo rather than installed, so Dependabot and `npm audit`
never see them. `/upgrade-deps` checks them by hand (step 2), and
`core/tests/test_static_assets.py` fails if the versions below stop matching
the files.

| File | Package | Version |
|---|---|---|
| `htmx.min.js` | `htmx.org` | 1.9.10 |
| `alpine.min.js` | `alpinejs` | 3.14.3 |
| `alpine-collapse.min.js` | `@alpinejs/collapse` | not recorded (the file carries no version); re-vendor it at Alpine's version on the next upgrade |

To update one, download the package's own minified build at the new version
(for example `https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js`), replace
the file, update this table, and check the rankings pages in a browser:
`scripts/browser_smoke.js` against `runserver`, at both widths. htmx 2 is a
major release with breaking changes (`hx-on`, extension loading, the
`htmx.config` defaults); take it deliberately, not as a bump.
