# Roadmap

What is left, why it matters, and what it costs. Ordered within each group.
`DEVLOG.md` records what has shipped; this file records what has not.

## Music: the last parity gaps

A mechanical diff of the games and music feature sets (every `aria-label`,
`title`, form field and control on each pair of pages) leaves two real gaps.
Everything else either matches or is genuinely games-only (platforms,
playtime, series).

1. ~~**Album tracking: `ListenedAlbum` / `WantToListenAlbum`.**~~ Done
   2026-10-18. The models, the toggle endpoint, the 48px column on both row
   halves, the Listen Status filter server- and client-side, and the detail
   page button. The button and the status filter were built as shared
   `core/` partials rather than a third copy of games'; games and books are
   untouched and can migrate to them. See AGENTS.md, "Album tracking".
2. **Saved filters.** Games has `SavedFilter`, the Saved dropdown, and the
   save/rename/delete modals in both the sidebar and the mobile sheet. Music
   has none. Worth less than tracking: the album filter state is smaller.
   **Now the top parity item.**

Not worth doing as parity:

- **Artist detail has no related-acts panel** where developer detail has a
  subsidiary filter. 0 of 616 artists in this corpus have sub-acts, so the
  panel would always be empty. Revisit only if the metadata pass starts
  filling `Artist.parent`.
- **Games' source-lists page still carries its own inline sort control**
  rather than `core/includes/_entity_sort_controls.html`. It looks identical;
  it is the last un-shared duplicate, so it is tidying, not parity.
- **Migrating games and books onto `core/includes/_tracking_button.html`**
  and `_status_filter.html`. The shared partials exist and are parameterised
  for it, but games' tracking button is working code with a 743-line suite
  behind it; the duplication costs nothing until one of them changes.

## Music: before it can launch publicly

3. **Nav entry and a `MUSIC_ENABLED` flag.** Today the only gate is
   `StaffOnlyMixin` raising 404 and the absence of any link. A flag gives a
   kill switch independent of staff status. ~2 hours.
4. **Discogs attribution terms.** Needs a human: their docs 403 automated
   fetches. Genres and styles come from Discogs, so the terms decide what the
   site has to display.
5. **Decide whether music gets SEO landing pages.** Games has
   `/games/<genre>/` and `/games/<decade>/`, crawlable and self-canonical,
   built from the same filter machinery. Music could, now that it shares the
   filters - but only once the section is public.

## Data pipeline

6. **Set `DISCOGS_TOKEN` on Heroku.** The metadata refresh is paced by the
   anonymous Discogs tier at 25 requests a minute, which is ~40 minutes for
   1000 albums. A token raises the ceiling and the client paces itself from
   the response headers either way.
7. **Schedule the music metadata refresh.** Games has a weekly refresh on the
   scheduler addon; music is run by hand. An import does not trigger it (on
   either section), which is now visible on the music import page.
8. **The MusicBrainz pass is opt-in and has never run on the new release.**
   `--musicbrainz` fills genres for the albums with no Discogs master - three
   of them in the previous release, unknown in this one.

## Production: the dyno is over its memory quota

11. **R14s are constant, not occasional.** As of 2026-10-18 the web dyno
    averages **96.4%** of its 512 MB quota, peaks at **112.7% (576 MB)**, and
    fires R14 in dense clusters right through the day, with H27 (client
    request interrupted) alongside - requests dying while the dyno swaps.

    The shape matters: this is **not** the sawtooth a classic leak draws
    (climb, restart, low floor, climb again). The line sits flat at ~460-470
    MB across a full 24 hours, including immediately after the deploys and
    restarts at ~3AM and ~3PM, and swap never exceeds 10 MB. That reads as a
    **baseline footprint larger than the quota** - several gunicorn workers
    each holding a big resident set - rather than something growing
    unboundedly over hours. Two recent changes plausibly raised the floor:
    the move of `default` to Postgres `DatabaseCache`, and the 1000-album
    release.

    Worth checking, roughly in order:

    - `WEB_CONCURRENCY` / worker count against a 512 MB quota, and whether
      gunicorn recycles workers at all (`--max-requests`). Three workers on
      512 MB leaves ~170 MB each.
    - Per-worker RSS at boot vs. after serving traffic. That one measurement
      separates "baseline too big" (buy a bigger dyno, or drop a worker)
      from "grows without bound" (find the retainer).
    - The in-process retainers: the `local` LocMem alias holds **whole
      rendered pages** (`CACHE_MIDDLEWARE_ALIAS`,
      `AnonymousResponseCacheMixin`) and its `MAX_ENTRIES` is per process,
      so three workers hold three copies; and `/api/music/all/` builds the
      entire 1000-album payload per request.

    Deliberately not guessed at further without measurements. Start with
    `heroku config`, the `Procfile`, and `heroku ps -a`.

## Housekeeping

9. `FORUM_ENABLED` is still set as a Heroku config var; the forum was removed
   in 2026-10-17. `MEDIA_URL` / `MEDIA_ROOT` have no consumer either.
10. `.git/hooks/pre-commit.legacy` runs `manage.py test games.tests` on every
    commit, on top of pytest. It has earned its keep - it caught a cache
    isolation bug pytest's conftest hid - but it is undocumented and roughly
    doubles commit time.

## Explicitly not doing

- **Books.** The client-side filtering stack was repaired on 2026-10-17 so it
  runs, but books still has no filter UI at all, and its sort controls
  reference an Alpine `filters` variable no component provides (5 console
  errors per page load). Deprioritized by the owner.
