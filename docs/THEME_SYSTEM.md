# Theme system

The site has two DaisyUI themes: **lofi** (light) and **forest** (dark).
They are declared in `theme/static_src/src/styles.css`:

```css
@plugin "daisyui" {
  themes: ["lofi", "forest"];
}
```

## Where the choice is kept

In two places, because the site is three origins (`acclaimedmedia.org`,
`games.` and `music.`):

- `localStorage` under `theme`, which is per origin.
- A `theme` cookie on the whole domain (`.acclaimedmedia.org`, one year), so
  a choice made on the games site follows the reader to music and the
  landing page. The cookie wins when the two disagree, since it is the
  latest choice made on any site.

On localhost there is no shared parent domain a cookie may name, so each of
`localhost`, `games.localhost` and `music.localhost` keeps its own choice.
The same goes for an address (`127.0.0.1`, which serves the games site):
its cookie is the host's own. Until 2026-11-12 the script named a domain
made of the address's last two parts (`.0.1`), which no browser keeps, so
there was no cookie there to write, and one already there could not be
changed and decided every page (see `core/tests/test_theme_cookie_js.py`).

There is one cookie. Saving the domain's removes a host's own of the same
name: a browser sends both, the older first, and the script reads the first.

## Page load

`games/templates/includes/_theme_script.html` is the first thing in
`base.html`'s `<head>`, which every page extends, the two import pages and
the landing page included. Before any CSS loads, it:

1. reads the cookie, else `localStorage` (inside `try`: with storage blocked
   the property itself throws);
2. accepts only `lofi` or `forest`, and otherwise takes the system
   preference (`prefers-color-scheme: light` is lofi, anything else forest);
3. writes the result back to both stores and sets `data-theme` on `<html>`.

So there is no flash of the wrong theme, and a value left over from an older
theme list is replaced on the next load.

## The toggle

The sidebar and mobile toggles are checkboxes with the `theme-controller`
class. One delegated `change` listener in `base.html` calls
`setTheme('forest' | 'lofi')`, which writes both stores, sets `data-theme`
and ticks both toggles. No reload.

## Django admin

The admin keeps Django's own styling and its own light/dark toggle. A custom
`admin/base_site.html` meant to apply the DaisyUI themes never took effect
(`django.contrib.admin` comes before `games` in `INSTALLED_APPS`, so its
template won), broke the header when switched on, and was deleted on
2026-10-26.

## Trying a theme by hand

In the browser console, on a page of the site:

```javascript
setTheme('lofi')    // or 'forest'
```

To go back to the system preference, clear both stores and reload:

```javascript
localStorage.removeItem('theme')
document.cookie = 'theme=;path=/;max-age=0'   // on production add ;domain=.acclaimedmedia.org
location.reload()
```

## Checklist after changing any of it

- [ ] The toggle switches between lofi and forest, on desktop and mobile
- [ ] The choice survives a reload and a move to another page
- [ ] In production, a choice made on one site holds on the other two
- [ ] A first visit follows the system's light or dark preference
- [ ] With cookies and storage blocked, the page still renders with a theme
