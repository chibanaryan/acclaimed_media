<!-- Part of the agent documentation. AGENTS.md keeps each section's rules
     and points here for the reasoning, history and measurements behind
     them. Moved out of AGENTS.md, word for word, on 2026-11-12. -->

# Album tracking

`ListenedAlbum` / `WantToListenAlbum` mirror games' `PlayedGame` /
`WantToPlayGame`, with four deliberate differences:

- **The button is one shared partial.** Games and books each carry their
  own; `core/includes/_tracking_button.html` takes the verbs,
  icons and route as parameters and `music/includes/_listen_button.html` is a
  thin wrapper supplying music's. Its dropdown is a menu (`role="menu"`,
  rows `menuitem`, on the clone twin too), walked by one stateless key
  listener in `media-tracking.js`: Enter opens it on its first item, the
  arrows wrap, Home and End, and Escape or Tab close it back to the button
  (2026-11-12; until then the button said `aria-haspopup` over a list with
  no role and no keys; smoke: "music listen menu by keyboard"). An arrow on
  a closed button opens it by clicking the button, so not in quick-mark
  mode, where that click marks (`_marks`), and not with Cmd, Ctrl or Alt
  held, which is the browser's chord. It resolves the route **positionally**
  (`{% url toggle_url_name item.id %}`) because `{% url %}` cannot take a
  dynamic kwarg name - so a section's toggle route must take the item's pk as
  its one positional argument. Games has since gone its own way, to one
  menu a page (`played-menu.js`, "Rankings page weight"), which this
  partial would have to learn before games could use it (ROADMAP).
- **No inline sync script.** Both other sections ship a `<script>` *inside*
  every swapped partial, which mutates the global Sets and then deletes its
  own earlier copies so they do not pile up. `core/js/media-tracking.js` is
  one delegated listener instead, and a page registers what its scope means.
  **Every page that renders the button includes
  `music/includes/_album_tracking_script.html`** in its `pre_alpine`
  block: the rankings, the album page and the artist page. The artist
  page had none until 2026-11-12, so a status chosen there left the row's
  hidden half on its old icon and dropped keyboard focus (smoke: "music
  artist page mirrors a status").
- **The toggle is atomic.** The delete and the write run in one transaction
  under a per-user lock, and `user_tracking_service.write_tracking_row` finds
  the user's row by tracking key or FK and updates it, so a double-click
  cannot race into an `IntegrityError`, a row orphaned when a release dropped
  its album is re-adopted on the spot, and one under an older key is renamed
  rather than left beside a second. The cache is dropped
  after the block commits, so a rolled-back write cannot clear it.
- **Nothing per-user goes in `/api/all/`.** That payload is held in
  `sessionStorage` keyed only on its version, so two people sharing a browser
  session share it. The client joins on the album pk, which the payload
  already carries, and the page renders `window.listenedAlbumIds` /
  `window.wantToListenAlbumIds` per request - so there is no new payload key
  and no `SCHEMA_VERSION` bump.

Two traps worth knowing, both of which only appear in a real browser and are
now pinned by `core/tests/test_media_tracking.py` and the source tests in
`music/tests/test_tracking.py`:

- **`htmx:afterSwap` is too early to read the new state.** With
  `hx-swap="outerHTML"` the swap *replaces* the target, so `detail.target` is
  by then the detached old element, still carrying its pre-swap
  `data-status`. `media-tracking.js` listens on `htmx:afterRequest` and takes
  the new status from the request's own `?status=`.
- **The client-side filter suppressor must only cancel GETs.**
  `album-client-filtering.js` cancels HTMX requests once the engine can answer
  them locally, with listeners on the form and on
  `#album-results-container`. Every row sits inside that container, so a
  row's toggle POST bubbles through the same listener - and cancelling it made
  the button do nothing at all, but only once the bundle had loaded, which is
  why it looked intermittent.

Two filter vocabularies, as games has: `?listened=own|yes|want|no`
(multi-select, comma-joined) for filtering, and `?status=own|listened|want|none`
for the toggle. `?listened=yes` reads correctly in a URL and
`data-status="listened"` reads correctly on an element;
`music/config.py:LISTEN_STATUS_OPTIONS` maps the two server-side and the scope
registry in `media-tracking.js` does client-side.

**Four exclusive states: Have, Heard, Want, Untracked.** Have was added
(2026-10-19) for readers who track what they own rather than what they have
heard, and "Listened" was relabelled "Heard" at the same time. The internal
spelling kept `listened` / `yes`, so old links, saved filters and
`mark_albums_listened` still mean "heard". Each state is exactly one thing
everywhere: `is_owned_by_user` and `is_listened_by_user` annotate
`owned=True` and `owned=False` rows respectively, `?listened=yes` leaves owned
albums out, and the page renders three disjoint Sets (`ownedAlbumIds`,
`listenedAlbumIds`, `wantToListenAlbumIds`), which `media-tracking.js` keeps
current through a status-to-Set map. The reconnection merge keeps `owned` if
any merged row had it. Have and Heard are illustrations, as games' Played is
its Mario Star: a gold record for Heard, and for Have that record sliding out
of its sleeve, so they differ by shape and not only colour
(`music/static/music/images/`). The shared button, its clone twin, the status
filter and the quick-mark picker take a static `image` in place of an icon
class. Untracked is `mdi-record-circle-outline`, and Want that empty record
with a plus, as games' Want is `mdi-star-plus-outline`: MDI has no record
with a plus, so `mdi-record-plus` is an SVG mask in `styles.css`, filled
with the text colour.

**Quick-mark mode.** A "Mark" button opens a menu of Have, Heard, Want,
Clear and Off (games: Played, Want to Play, Clear, Off). With a mode picked,
one click on a tracking button applies that status, and a click on an item
already in it clears it. The button shows the mode's icon and is tinted while
one is on. It is `core/includes/_quick_mark_picker.html` and
`core/js/quick-mark.js`, which both rankings pages push onto
`window.alpineScripts`. On desktop `_media_list_controls.html` includes it
when the page passes `quick_mark_scope` and `quick_mark_options`, on the
right beside jump-to-rank. That row is a three-column grid
(`minmax(max-content,1fr) minmax(0,1fr) minmax(max-content,1fr)`), so the
count sits at the true centre. Below xl, words give way to icons (Asc, the
Mark label), and a container query hides the count once the middle column is
too narrow for it, rather than truncating it to a stray letter. On mobile
it sits beside the Filters button, because the controls row is already full
at 360px. It was first a strip of five buttons in the results header, which
crowded that row. Four things it depends on:

- The mode is per scope in `localStorage` (`quickMark:<scope>`) and acts only
  while a picker for that scope is on the page, so detail pages keep the menu.
- Its click listener **captures**, for the same reason the played menu's
  does: the button's Alpine handler would open the menu and the wrapper stops
  propagation in the bubble phase.
- It ignores `event.detail >= 2`: the second click of a double-click would
  otherwise undo the first.
- It posts with the wrapper as source and target, to the wrapper's
  `data-toggle-url` (games: the played menu's `data-url`), so the swap goes
  through the same path as a menu choice. Games' `played-menu.js` asks
  `QuickMark.active('game')` before opening its shared menu.

Per-user cache keys cannot live in `CACHE_KEYS`, which is a flat tuple an
import iterates. They are templates in `PER_USER_CACHE_KEY_TEMPLATES`, dropped
by `caching.invalidate_listen_caches(user_ids)` on a toggle and from the bulk
command below, by `invalidate_release_caches(user_ids)` on an import, and by
`music/signals.py` for a row changed any other way, such as in the admin.

**The Account modal shows a reader's albums** beside their games, the current
site's block first, on any host (`music.services.listening_stats`). Its rank
counts Have and Heard together, and so
says "tracked" rather than "heard", which would be false of a reader who only
marks what they own. The rank logic is `core.services.percentile`, shared with
games: a percentage compares a reader with everyone else, "top 1%" counts those
level with or ahead of them, so a tie cannot claim it, and a leader or someone
near the bottom gets a position instead, "tied for" when it is shared, since
"more than 95%" undersells the first and "more than 0%" says nothing to the
second. `CACHE_KEY_LISTENER_COUNTS` is one global key, in `CACHE_KEYS` for
an import, and `invalidate_listen_caches` drops it too, for a toggle or the bulk
command. `music/signals.py` covers the rest, as games' signals do
(2026-11-09): a tracking row saved or deleted anywhere drops its reader's sets
and the counts, which a deleted user's cascade reaches too, and an album,
artist, credit, list or publication added or deleted drops the section's
`CACHE_KEYS`. Until then an admin edit waited out an hour for the counts and
a day for the heading's. Each drop waits for the commit and is folded into
one, the toggle's and the bulk command's own with it (they queue theirs
inside their transaction for that), so a click is one drop and an import pays
one more at its commit. An album's year or genres changed in the admin, a tracking
row given to another reader and an album deleted with rows on it are covered
too (2026-11-10). A changed year or reader is seen without a query:
`core.loaded_values.RemembersLoaded` keeps a row's `remembered_fields` as
the database last had them, so `post_save` can ask what changed. Reading the
old row in `pre_save` would be a query on every save, and the metadata
passes save every album. Games' year counts follow a game's year the same
way.

**Marking a collection in bulk**, for importing listens matched elsewhere
(a RateYourMusic export, say) without several hundred web requests:

```bash
python manage.py mark_albums_listened --user <name> --ids Q212863,Q19003
python manage.py mark_albums_listened --user <name> --ids-file ids.txt --dry-run
```

The matching stays outside the command. Deciding that an export's
"E·MO·TION" is our "Emotion" is a judgement call for whoever is looking at
both lists; the command takes the Wikidata ids that judgement produced and
does only the database half, with the toggle's own semantics - one
transaction, `update_or_create` on the `unique_together`, any
want-to-listen row for the same album cleared, and the per-user caches
dropped on commit. An id already marked is left alone, so a mark the user
made themselves keeps its `created` timestamp, and ids are matched against
every id an album carries rather than just the primary one.

**The User admin shows all five tracking counts** (played, want to play,
have, heard, want to listen) with a read-only capped list of each. Have and
Heard are both `ListenedAlbum` counts, split on `owned`, and the
`ListenedAlbum` changelist filters on it, since Have has no table to find
in the admin sidebar. The counts
are correlated subqueries, not `Count("relation", distinct=True)`: four
multi-valued joins on one queryset multiply, and a user with 822 listened
albums and 178 want-to-listen rows produced 146k intermediate rows before
`distinct` collapsed them again.
