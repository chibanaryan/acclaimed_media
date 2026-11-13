# Roadmap

What is left, why it matters, and what it costs. `DEVLOG.md` records what
has shipped; this file records what has not.

**What belongs here.** An entry is something that would be fixed, or
decided, by whoever next had a free hour for it. A nit in a staff command,
a measurement that came out "not worth it", a parked section's leftovers:
none of those is an entry. Say it in the commit message, or add a line to
"Known, not planned" if a later pass is likely to find it again. A pass
that files more than it closes says so, with both numbers.

This file was triaged on 2026-11-13. Six improvement passes in eleven days
had taken it from 2 open bug entries to 39, and from 1 production check to
21, while each closed ten to fifteen: every pass ran new audits and filed
all they found. Read against production that day, 12 of the 21 checks were
closed (the readings are below), 4 are Sunday's and 5 are the owner's. The
bug entries struck are one line each under "Known, not planned"; their
full text is in `git show 55f0be4e:ROADMAP.md`.

## Open bugs

1. **Three name-searched games hold an HLTB entry a search no longer
   gives.** The weekly job will move them: Call of Duty: Modern Warfare 2
   (stored entry 109060, 8.2 h; a search gives 1477, 6.6 h), Puyo Puyo
   (83379, 0.5 h; 9411, 1.2 h) and "Bomberman / Atomic Punk / Dynablaster"
   (1230, 2.4 h; 1244, which is Bomberman II, 2.0 h). The last is a wrong
   match by name. Giving each its HLTB id on Wikidata (P2816) settles it
   for good, since an id is looked up before any name.

## For the owner

2. **New brand artwork.** The favicons still read "Acclaimed Video Games"
   (`games/static/games/brand/`), and a page without artwork of its own has
   no `og:image`. A new default goes in `base.html`'s `og_image` block, and
   the five templates overriding that block need a `{{ block.super }}`
   branch for items with no art.
3. **Look once, when the occasion comes.**
   - A sign-up, end to end: the confirmation link logs in only the browser
     that signed up. Open it there (logged in) and in another browser
     (verified, with a Log In button).
   - A notification email's headers, the next time a post goes out: Gmail
     and Apple Mail should show their own Unsubscribe control, and the
     footer link should ask before it unsubscribes.
   - The staff import page, at the next import: its progress bars have a
     fill for the first time since DaisyUI 5, and the IGDB stream sends a
     keepalive every 15 seconds.

## After Sunday 2026-11-15's jobs

4. **Read both weekly jobs once.** It is the first Sunday since five of
   the passes shipped. All of it can be read from Sentry and a one-off
   dyno:
   - `refresh-all-metadata` checked in green. It now fails when a phase
     could not run at all, and its output names the phase. Its Wikipedia
     phase sends the credentials it paces itself by, so it should see no
     429s.
   - Its HLTB phase moved Wordle and the three games in bug 1.
   - `/api/games/all/`'s data version moved only if a phase changed what
     the pages show.
   - `IGDBGameData.summary` is filled (0 of 1,400 on 2026-11-13; the
     column shipped in v924), and a game page's
     `<meta name="description">` leads with its rank and goes on in IGDB's
     words. `heroku run:detached -- python manage.py get_igdb --force`
     fills it sooner.
   - The music job's log: an album's failure in the cover, Discogs or
     MusicBrainz pass is an error line and the pass goes on. Many of them
     are a source down, not many bad albums.

## After the next deploy

5. **Drop two columns.** IGDB's first video and the Wikiquote title were
   fetched and shown nowhere; the code and the models stopped naming them
   on 2026-11-13 (`games.0126`, in Django's state only, so that the release
   before it and a rollback to it keep working). Once that release is
   live, a migration drops `games_igdbgamedata.youtube_video_id` and
   `games_wikipediagamedata.wikiquote_page_title` (`RunSQL`: the state no
   longer has them). It checks that each column is there first: SQLite
   drops them by itself the next time a migration remakes either table.

## Production, as read on 2026-11-13

The numbers the next reading is compared with. Sentry samples one request
in ten; its counts are scaled.

- **Errors.** Nothing is unresolved in thirty days but browser
  extensions' CSP reports and one outage: the database restarted on
  2026-11-12, 22:45 to 22:49 UTC, and 78 requests failed to connect. It was Heroku's restart, nine minutes
  before v923 and not a deploy's doing. An essential-tier database has no
  standby and no maintenance window to choose.
- **Uptime.** No downtime issue in thirty days.
- **The scraper's bursts go on**, daily: about 6,400 to 7,000 requests in
  the 21:00 UTC hour and a second burst between 02:00 and 05:00, against
  about 1,500 an hour otherwise. The kept pages answer them: `/`'s p50 was
  79 ms across a seven-hour window that held one.
- **The render budget has reported nothing to Sentry** since it shipped,
  so no burst has gone 100 renders over it in a worker (an application
  logger's errors do arrive: music's have).
  `ANON_RENDER_BUDGET_ENFORCE` stays off, with nothing to enforce against.
  Turn it on if "Anonymous renders over budget" ever appears in Sentry.
- **`/`'s p50 by release** (all three hosts' `/` together): 260 ms before
  v919, 77 ms on v919, 104 on v920, 109 on v921 and 80 on v922, the fifth
  pass's, which took the `DISTINCT` off the rankings' list query.
- **Memory**, under `--max-requests 2000`: over 72 hours the web dyno
  peaked at 356 MiB RSS of the 512 MiB quota (median 297), with no swap.
  It stays. An import's metadata fetch spends about 85 MB more.
- **Accounts.** None of 295 has a username holding an `@` that is not its
  own email, so the old sign-up page left no squatted address; and every
  allauth address row is for its account's own email
  (`repair_email_rows` found nothing to repair).
- **Migrations.** `games.0124`, `music.0015` and `games.0125` are applied.
  `games.0126` goes with the next deploy and changes no table (entry 5).
- **The shared venv** matches the locks again (Django 6.1.3, allauth
  65.21.0, soupsieve 4.1).

## Known, not planned

Found by one pass or another and left on purpose. A line each, so the next
pass that finds one knows it is known; do not file these again without a
new reason.

- **Nothing has been heard through a screen reader or run on a real
  iPhone**, and the owner will not be doing it (2026-11-13). The pages
  were checked by keyboard, with axe-core and against Chrome's
  accessibility tree, which is what there is. The checklist written for
  the run was removed that day (`git log -- docs/ASSISTIVE_TECH_CHECKLIST.md`).
  Two things were waiting on it and stay as they are: the search boxes are
  comboboxes, and a year cell reads "10" while its name is "2010, 12
  albums" (WCAG 2.5.3 would have "10: 2010, 12 albums", about seventy
  longer announcements a page).
- **The music job has no cron monitor in Sentry**, by the owner's choice
  (2026-11-13): the free plan includes one, and the games job has it. The
  music job's errors reach Sentry; a Sunday it does not run at all alerts
  nobody.
- **Books**, all of it: parked by the owner. Its client engine was removed
  on 2026-11-12 and the server renders its list. The sort dropdown, the
  direction flip, the jump box and an author's Load More are inert; the
  read button has no icon and no name; nothing drops a books cache; the
  authors list pushes its own history entry.
- **A `?highlight=` landing can miss when an import commits during the
  page's load.** Three edges, each needing a page load to straddle an
  import. Six review rounds went into this case.
- **A failed Back, then a failed change, with no engine**: three failures
  in a row, in `_rollBackIfStranded`, the function that has cost the most
  review rounds.
- **An article's featured image has no box before it loads.** Production
  has no articles (2026-11-13). Store the dimensions when one is written.
- **Music's artist and genre filters still join and `DISTINCT`**, on a
  thousand rows, with nothing measured to say it matters. Album detail's
  two `COUNT`s: the cache read would cost the query it saves. A metadata
  pass reads an album's rows twice, which is what lets its step cope with
  a row another run changed.
- **Music's listen button is a dropdown a row**, some 400 KB of a
  signed-in rankings page by a rough count, where games has one menu a
  page. Measure before rewriting it. Games' tracking button stays its own
  until the shared partial learns that design.
- **`base.html`'s inline script**: a few kilobytes on a repeat visit.
- **Music's takeover has no `catch`**: one that only logged would hide an
  error the smoke test fails on.
- **Staff-written markdown is rendered unsanitized.** Fine while only
  staff write it.
- **`USE_TZ = False`**, correct only because `TIME_ZONE` is UTC. Turning it
  on is a migration project.
- **`Retry-After` in the music client**: tried on 2026-11-12 and taken out
  at its second review round. One request of the cover pass is still made
  inside its savepoint.
- **A `theme` cookie this site did not write can win** on a shared local
  address or across hosts. `am_theme` would end it, at one reset of every
  reader's choice.
- **The games metadata commands' edges**: a game's alternate Wikipedia
  record does not survive an import; the weekly refresh has its own copy
  of the page save and of the infobox parser, and counts a failed save
  twice; `aiohttp.BasicAuth` goes in aiohttp 4.0; flag oddities in
  `fetch_wikipedia_metadata`, `get_wiki_genres` and `fetch_hltb_data`.
- **`games/static/games/palestine-flag-xs.png`** is linked from nothing in
  the repository or in production's articles, posts, snippets and flat
  pages (2026-11-13). Kept: something outside the site may link it.
- **The commit and deploy skills' DEVLOG rules** (eight bullets a day, the
  imperative) are not what `DEVLOG.md` has looked like since October.
- **Nothing runs WebKit or Firefox.** The smoke test is Chrome alone;
  Firefox would not start headless from the agent's shell on 2026-11-12.
- **Artist detail has no related-acts panel**: 0 of 629 artists have
  sub-acts.

## Known divergences, deliberate for now

- **The games rankings heading ignores the search query, on both sides.**
  `_build_filter_title` and `_buildDynamicTitle` both leave `?q=` out, so
  searching does not change the heading; music names the query instead
  ("Albums matching ..."). The two games halves agree with each other, which
  is the property that matters, so this is a wording difference rather than
  a bug. Align only if the album phrasing is judged better.
- **The album page's sub-heading counts are corpus-wide, not filtered.**
  "The top 1,000 most recommended albums across 54 critic lists" stays put
  while the heading above it narrows to a genre. Games has no filtered
  equivalent either, and the filtered count is already shown on the results
  line.
