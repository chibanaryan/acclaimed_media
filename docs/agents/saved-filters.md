<!-- Part of the agent documentation. AGENTS.md keeps each section's rules
     and points here for the reasoning, history and measurements behind
     them. Moved out of AGENTS.md, word for word, on 2026-11-12. -->

# Saved filters

A reader who has built up a genre + decade + listen-status combination keeps
it by name. Games has had this since `SavedFilterSet`; music's was built as
**shared `core/` components with music wired to them**, the way album
tracking was, lifted from games' markup. Games took the three includes in
place of its own copies on 2026-11-12, so both sites render one set
(smoke: "games saved filters").

| Piece | Where |
|---|---|
| `core.models.SavedFilterSetBase` | abstract: user, name, `filters` JSON, created/modified, `-modified` ordering |
| `music.models.SavedAlbumFilterSet` | the concrete table; adds nothing |
| `core/includes/_saved_filters_dropdown.html` | the sidebar "Saved" menu |
| `core/includes/_saved_filter_modals.html` | save / rename / delete, one copy per page |
| `core/includes/_mobile_saved_filters.html` | the bottom sheet's collapsible equivalent |
| `core/js/media-list-controls.js` | the state and the eight methods, named as games' are |
| `/api/saved-filters/` (music host) | list, create, rename, delete |

The partials bind to a **method contract**, not to a page:
`loadSavedFilters`, `applySavedFilter`, `saveCurrentFilters`,
`submitSaveFilter`, `renameSavedFilter`, `submitRenameFilter`,
`deleteSavedFilter`, `confirmDeleteFilter`, plus `hasActiveFilters` and
`savedFilters*`. Both `mediaListControls` and games' `filterComponent`
expose exactly those names, which is what made games' migration a template
change. On `mediaListControls` the whole feature is inert unless the page
passes a `savedFiltersUrl`, so a section that has not opted in renders no
button; games' component names its own endpoint.

Both sites' write views parse the body with
`core.services.request_body.SavedFilterJSONParser`, which refuses one over
16 KB before parsing it: DRF reads the stream itself, so Django's
`DATA_UPLOAD_MAX_MEMORY_SIZE` never applied. They read it through
`read_saved_filter`, which never raises: a name
of `null` or a body that is an array was a 500 on games, and music saved
`null` as a filter called "None". A number is taken as its digits; anything
else is the "name is required" 400, and filters that are not an object are
a 400 too.

Four things worth knowing before changing any of it:

- **Applying a saved filter must not announce `genres-reset`.** That event
  does not mean "refresh yourselves": `_mobile_filter_genres.html` answers it
  by assigning `[]`, and **the mobile sheet shares the rankings page's Alpine
  state at every width, desktop included**. So dispatching it after restoring
  a combination wiped it: the sort and its direction survived while the genre
  was silently dropped, and the heading went on naming the unfiltered page.
  `year-reset` did the same to the years, here and on Back, and went on
  2026-11-01. The grid and the tree derive their selected state from `filters`
  reactively and need no telling. Pinned by
  `core/tests/test_static_bundles.py::ApplyingASavedFilterMustNotAnnounceAResetTests`.
- **`applyingSavedFilter` was a hook with nothing on the other end.**
  `core/includes/_year_grid.html` has always passed `isApplyingSavedFilter`
  behind a `typeof` guard, so a component without the flag silently got
  `false` and the grid treated a programmatic range as a hover preview.
  Defining it on `mediaListControls` lit the hook up with no template
  change - and the guard is why its absence could never throw.
- **This is music's first *write* endpoint**, so CSRF applies to
  `music/api/` for the first time; `MusicWriteAPIMixin` sits beside
  `MusicReadAPIMixin` to say which views that covers. A signed-out caller
  gets games' 403. The ordinary Django test client does not enforce CSRF, so
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
