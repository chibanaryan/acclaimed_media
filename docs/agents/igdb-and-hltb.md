<!-- Part of the agent documentation. AGENTS.md keeps each section's rules
     and points here for the reasoning, history and measurements behind
     them. Moved out of AGENTS.md, word for word, on 2026-11-12. -->

# IGDB Integration

The `games/igdb.py` module handles IGDB API integration with multiple optimization strategies:

### Features

**Field Expansion**: Reduces API calls by 3-5x by expanding cover and genre data in the main game query instead of making separate requests.

**Concurrent Requests**: Process multiple games simultaneously (up to 8 concurrent requests) for 4-8x speedup.

**Multi-Query Batching**: Fetch multiple games per API request (10-50 for free tier, up to 500 for Pro tier) for additional 3-5x speedup.

**Pro Tier Support**: Access IGDB Pro tier with 750x faster rate limits (3,000 req/sec vs 4 req/sec).

**Thread-Safe**: All caching and rate limiting is thread-safe for concurrent processing.

IGDB provides cover art, descriptions, developer information, and genres.

**A game page's description is IGDB's summary** (2026-11-12). Every fetch
asked for it and dropped it, so each page had one stock sentence. It is
`IGDBGameData.summary`, written by both branches of the fetch, and the
page's meta description and share card lead with the rank and go on in its
words, cut at a whole word within 160 characters (`seo.meta_description`);
the JSON-LD carries all of it. A description staff wrote on the `Game`
comes first. `needing_igdb()` does not count a missing summary: IGDB has
none for some games.

A single game's lookup (`IgbdApi.get_game_info_by_id`, `Game.get_igdb_data`)
answers `None` for a failure of ours or IGDB's (a timeout, an error status,
a 401 after one new token) and raises `GameNotFound` for an id IGDB has
dropped or merged. The admin's Save keeps the edit and says so; the importer
names it "Not found in IGDB response". Every request carries
`igdb.REQUEST_TIMEOUT`: without one, a connection IGDB accepted and never
answered held its thread and the metadata lock for good.

For detailed command usage, run `/igdb`.

## HowLongToBeat playtimes

Rows, cards, the playtime sort and filter show HLTB's **Main Story** average,
or **100%** with the toggle; Main + Extras appears only on the detail page and
in the CSV.

**Open-ended games show no playtime.** For League of Legends, World of
Warcraft or Rocket League, HLTB's averages are time invested, not time to
beat. They put a 1162-hour MOBA at the top of "longest" and a five-hour
car-football game under "short". `HLTBGameData.is_open_ended` is derived in
`save()`: the staff call in `open_ended_override`, else HLTB's own
`game_type` (`multi`/`endless`/`sports`, read from the raw search row by
`fetch_hltb_data.entry_profile`). `games/services/playtime.py` is the one
place that applies it: the sort, the filters and their counts,
`/api/games/all/` (null `pt`/`ptc`), the `hltb_hours` tag, the `shown_hltb`
filter on the row `{% with %}`, the backlog total and the CSV. The detail
page keeps the numbers under a "No finish line" line.

**The calls are made in the admin**, on the HLTB record: the override's help
text states the test (does the game have an ending that HLTB's Main time
measures?), and the HLTB changelist has bulk "Mark open-ended / Mark
finishable / Clear the call" actions; the Game changelist shows the result
as a read-only "Open-ended" column, with a filter for games HLTB has not
matched (which cannot carry a call yet). A call reaches visitors on their
next page: the data version that cached pages and `/api/games/all/` are
kept under fingerprints the open-ended set. If
IGDB re-keys a game, the fetch gives its new HLTB row the old row's call.
HLTB files most sandbox, sports and
arcade games as ordinary "game"s and some co-op story games as "multi", so
about 190 calls were made by hand; migration `0120` moved them there from a
list in code (`games/open_ended.py`, deleted). The call lives on the HLTB
record, not on `Game`, because a games import recreates every `Game` while
HLTB rows survive it and every refresh. A game with no HLTB row yet cannot
be marked until HLTB matches it. `comp_lvl_combine` is stored but not used:
production's first full refresh showed it marks any game with a co-op or
versus mode (Sam & Max, Gunstar Heroes), and it was hiding story games.
Never `.update()` the override or `game_type` without re-saving, which
re-derives the flag.

The weekly `refresh_all_metadata` refetches every game and so fills in the
flags. It fails (`CommandError`) when a phase could not run at all, after its
summary and after the metadata lock is let go: each phase catches its own
error so the others go on, and until 2026-11-10 it exited 0 with all three
FAILED, which Sentry's cron monitor read as a good Sunday. Errors on some
games do not fail it. HLTB answers a burst with 429s; a failed lookup leaves the row as it
was. Its Wikipedia phase sends the Wikidata credentials it paces itself by
(`wikidata_credentials`): until 2026-11-10 it took the authenticated rate
for any token and sent none, and its requests had aiohttp's five-minute
timeout, now 30 seconds.

**Which HLTB entry a game gets** is `games/services/hltb_matching.py`, for
`fetch_hltb_data` and the weekly job alike (each had a copy until
2026-11-10). A game is looked up by the HLTB id Wikidata holds; 53 of 1,400
have none and are searched for by name, Wikipedia's title first. A name
search's entries are narrowed by similarity, then release year (within one),
then platform, each only while several are left and only if it leaves any.
The platform step never ran before 2026-11-10: it read `profile_platform`,
and howlongtobeatpy's entry has `profile_platforms`, a list. A platform is
matched by its whole name through `PLATFORM_ALIASES` (HLTB's name to ours):
looked for anywhere in the name, "playstation" answered for PlayStation 4.
Run against all 88 name-searched games that day, it changed one entry:
Wordle, from the 2020 mobile game to the 2021 browser one. The `/api/games/all/` version hash fingerprints the playtimes it serves
(summed hours, and the ids of open-ended games). An HLTB save leaves
`Game.modified` alone, and the weekly refresh saves every row whether or not
anything changed, so `updated_at` would make every visitor re-download the
data each week. For the same reason the weekly job moves the version only
if it changed what the pages show (2026-11-12): its IGDB and Wikipedia
phases write genres, slugs and artwork through saves that leave
`Game.modified` alone, so until then nothing told a reader's stored
payload, which has no age limit. `refresh_all_metadata` fingerprints the
payload before and after (`post_import.payload_fingerprint`) and calls
`move_data_version()` if they differ or cannot be compared.
