<!-- Part of the agent documentation. AGENTS.md keeps each section's rules
     and points here for the reasoning, history and measurements behind
     them. Moved out of AGENTS.md, word for word, on 2026-11-12. -->

# Shared ranking-page components

The games and album rankings pages render the same chrome from `core/`. They
had each grown their own, and the album page's was visibly poorer for it - a
row of decade chips instead of the year heatmap, a flat `<select>` where a
root genre and one of its styles looked identical, no view toggle, no
jump-to-rank, and row styling that had copied the games hover rules without
the hover.

| Shared piece | What it is |
|---|---|
| `core/includes/_media_list_controls.html` | sort dropdown, direction flip, list/grid toggle, jump-to-rank |
| `core/includes/_year_grid.html` | the year heatmap, with drag and shift+click ranges |
| `core/includes/_genre_filter.html` | the hierarchical genre tree |
| `core/includes/_mobile_filter_time.html`, `_mobile_filter_genres.html` | their bottom-sheet equivalents |
| `core/includes/_entity_sort_controls.html` | the sort control for entity lists (artists, source lists, developers) |
| `core/includes/_publication_group.html` | a publication's lists, collapsible, on a source-lists page |
| `core/includes/_list_type_group.html` | one group of list appearances on a detail page |
| `core/includes/_rank_distribution.html` | where the filtered items sit across the ranking |
| `core/includes/_search_box.html` | the standard search input, with its clear button |
| `core/includes/_search_combobox.html` | a section's search box (the sidebar's and the mobile bar's): the combobox field, hints and listbox, with each site's option rows in its own `_search_options.html` |
| `core/includes/_tracking_button.html` | the three-state tracking dropdown, and `_tracking_button_template.html`, its clone twin |
| `core/includes/_status_filter.html`, `_mobile_filter_status.html` | the tracking status filter, games and music alike since 2026-10-29: each option shows its button's mark in its colours (`GAME_STATUS_OPTIONS`, `LISTEN_STATUS_OPTIONS`) |
| `core/includes/_saved_filters_dropdown.html`, `_saved_filter_modals.html`, `_mobile_saved_filters.html` | saved filter combinations, in the sidebar and the sheet, on both sites |
| `core/services/titles.py` | the heading's wording: `join_names`, `build_time_window` |
| `core/services/ranking.py` | `rank_distribution`, the chart's binning |
| `core/js/filter-subcomponents.js` | `yearGridComponent`, `genreFilterComponent` and their mobile forms |
| `core/js/media-list-controls.js` | `mediaListControls`, `entityListControls` |
| `core/js/media-search.js` | `createMediaSearchData`, for a section's search box |
| `core/js/media-tracking.js` | `MediaTracking`, which keeps the tracking id Sets current after a button swap |
| `core/includes/_quick_mark_picker.html`, `core/js/quick-mark.js` | quick-mark mode: one click applies a picked status (see "Album tracking") |
| `core/js/media-list-controls.js` | also the saved-filter state and methods, inert without a `savedFiltersUrl` |

The templates are the contract. Each binds to an Alpine component exposing
`filters`, `genres`, `initialized`, `debouncedFilterUpdate()`,
`handleFilterChange()`, `updateSort()`, `toggleSortDirection()`, `viewMode`
and `setViewMode()`. Games satisfies it with `filterComponent`, which also
owns platforms, series, playtime and saved filters; music satisfies it with
`mediaListControls`, which writes the state into its HTMX form and announces
a `change`. **Add a control to the shared template, not to one page.**

Row and card styling is shared the same way but through CSS selector lists -
`.game-row, .media-row { ... }` - because each section's JavaScript queries
its own class names. One rule block, both families; a fourth copy of the
`.game-row` rules is what left album rows without a hover state.

A selected year range reads as one shape, and fades as one, because each tile
(a decade label or a year cell, `.year-grid-tile`) carries four generated boxes
in the primary colour: its fill over the heatmap colour, the gaps to its left
and above, and the corner between them. Each gap has one owner because two
half-opaque boxes stack, and it is the later tile, which paints over both
neighbours. That is why `yearExists` counts the zero-count years `buildDecades`
fills in. All four fade `opacity`, which runs off the main thread in every
browser. A filter change's list render blocks that thread, so a fade on it
waits: with box-shadow gaps, and again with `background-color` on the boxes,
Clear finished the tiles at ~220 ms and started the gaps at ~550-640 ms (4x
CPU). Text colour changes at once for the same reason, and unavailable tiles
are grey by background, since a `filter` would grey a leaving fill. The gaps
take two thirds of the fill's fade, leaving first and arriving last. In exact
step they still looked as if they lingered: at 127 ms of a Clear the tile was
`147,139,79`, already tan, and the gap `169,192,186`, still green, because the
primary colour stays itself over the page background and turns muddy over the
heatmap. Gaps at 80 ms overshoot, and the range falls apart before it fades.
Two things are steps at the far end of a fade: a fill's corners round off when it
has gone, since rounding them while solid opened a star at every join, and a gap
reaches a pixel over both neighbours once it has arrived, since meeting exactly
left a hairline at any fractional display scale (browser zoom 110%, Windows at
125%, which 1x and 2x hide). A range is `.is-in-range`, not the shared
`.is-selected`, whose ring and tint only source order would keep off. Measure
all this from real frames after a real click, and look at them: freezing a
transition takes the threads out of the picture, and a matching percentage is
not a matching colour. Pinned by
`core/tests/test_static_bundles.py::YearGridGapsFadeWithTheirTilesTests`.

Facet counts (the number beside a year cell or a genre row) are counted with
their own dimension left out, so an option never leads to an empty page:
`apply_album_filters(..., skip=("year",))` server-side and
`AlbumFilterEngine.facets()` in the browser. Both publish the same
`year-counts-update` / `genre-counts-update` events the subcomponents listen
for, so neither side knows which did the counting.
