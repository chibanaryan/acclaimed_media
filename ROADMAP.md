# Roadmap

What is left, why it matters, and what it costs. Ordered within each group.
`DEVLOG.md` records what has shipped; this file records what has not.

## Music: the last parity gaps

A mechanical diff of the games and music feature sets (every `aria-label`,
`title`, form field and control on each pair of pages) leaves two real gaps.
Everything else either matches or is genuinely games-only (platforms,
playtime, series).

1. **Album tracking: `ListenedAlbum` / `WantToListenAlbum`.** The last
   structural difference. It unlocks the Game Status filter's equivalent, the
   star column at the left of every row, and the tracking button on the detail
   page - which is why games rows reserve 48px that album rows do not. Model
   the pair on `PlayedGame` / `WantToPlayGame`; the row renderer already has
   the slot pattern. ~1 session.
2. **Saved filters.** Games has `SavedFilter`, the Saved dropdown, and the
   save/rename/delete modals in both the sidebar and the mobile sheet. Music
   has none. Worth less than tracking: the album filter state is smaller.

Not worth doing as parity:

- **Artist detail has no related-acts panel** where developer detail has a
  subsidiary filter. 0 of 616 artists in this corpus have sub-acts, so the
  panel would always be empty. Revisit only if the metadata pass starts
  filling `Artist.parent`.
- **Games' source-lists page still carries its own inline sort control**
  rather than `core/includes/_entity_sort_controls.html`. It looks identical;
  it is the last un-shared duplicate, so it is tidying, not parity.

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
