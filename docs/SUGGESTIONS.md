# Suggestions: Growing AVG into the definitive acclaim reference

The goal: when anyone wants to know "what are the best [platform/genre/era] games according to critics," they come to AVG. Not Metacritic, not OpenCritic. AVG should be the first resource anyone uses when talking about a game's overall level of acclaim, and the best-known resource for it.

Right now, AVG has ~80-100 users/day. The target is 1,000+/day. Here's what I think gets us there.

---

## 1. SEO landing pages (the biggest gap)

This is the single highest-impact thing we can build. Right now, all filtering happens client-side via JavaScript and query strings. Search engines can't index any of it. When someone googles "best SNES games of all time" or "best RPGs ever," there's no AVG page for Google to serve.

Metacritic and OpenCritic rank for these queries because they have dedicated, crawlable HTML pages for every platform and genre. We need the same thing, but better.

### What to build

**Platform landing pages** — `/platforms/snes/`, `/platforms/ps2/`, `/platforms/switch/`, etc.
- Server-rendered HTML page for each platform in the database
- Title tag like "Best SNES Games of All Time | AcclaimedVideoGames"
- Shows the top N games for that platform, ranked, with cover art
- Brief intro paragraph (can be templated: "{count} games from {platform_name} appear in our rankings, drawn from {list_count} critic lists...")
- Links to individual game detail pages
- Paginated or "load more" for the full list
- Crosslinks to related platforms (e.g., SNES page links to NES, N64, Game Boy)

**Genre landing pages** — `/genres/rpg/`, `/genres/platformer/`, `/genres/metroidvania/`, etc.
- Same structure as platform pages
- Use the WikipediaGenre hierarchy: parent genre pages link to child genres
- "Best RPGs" should also show sub-genres like "Action RPG," "JRPG," "Tactical RPG" with their own pages

**Decade/year landing pages** — `/decades/1990s/`, `/years/1998/`, etc.
- "Best games of the 90s," "Best games of 1998"
- These are high-traffic search queries, especially for nostalgia content
- Year pages should show year_rank ordering

**Combo pages** (stretch goal) — `/platforms/snes/genres/rpg/`, `/decades/1990s/platforms/ps1/`
- "Best SNES RPGs," "Best PS1 games of the 90s"
- These long-tail queries have less competition and high intent
- Can be generated programmatically from the existing filter logic
- Only generate combos that have enough games to be useful (e.g., 10+ results)

### Implementation notes

- The Platform model already exists with code, name, year_start, year_end
- WikipediaGenre has hierarchical parent-child structure (level 0 = root categories)
- Games already have decade_rank and year_rank fields
- The filtering logic in HomePageView already handles all of these queries — the landing pages can reuse that logic but with their own URL routes and templates
- Add these to sitemaps.py (currently only has static, games, developers, books, authors)
- robots.txt already exists, just needs to not block the new paths
- Use `<link rel="canonical">` on each landing page to avoid duplicate content issues with the query-string-based filtering on the homepage

### SEO details

- Each page needs a unique `<title>` and `<meta name="description">`
- Structured data (JSON-LD): ItemList schema for ranked lists, VideoGame schema on game details
- Internal linking: every game detail page should link back to its platform/genre/decade pages
- The homepage should link to popular platform and genre pages (helps crawlers discover them)
- Consider an HTML sitemap page that lists all browse categories

---

## 2. Individual game pages as the acclaim reference

When someone googles "Chrono Trigger acclaim" or "is Breath of the Wild one of the best games ever," the AVG game detail page should be what comes up. These pages already exist (`/game/<slug>/`), but they could do more to own the "acclaim" angle.

### What to add

- **Acclaim percentile** — "Ranked #14 out of 1,247 games (top 1.1%)" is more shareable and quotable than just "#14"
- **How many lists it appears on** — "Appears on 87 of 142 all-time lists" with a breakdown by list type
- **Acclaim trajectory** — if we track ranking changes over time, showing "entered the ranking at #45 in 2020, now at #14" tells a story
- **Embeddable badge/widget** — a small image or HTML snippet that says "Ranked #14 on AcclaimedVideoGames.com" that game journalists, bloggers, and forum users can embed. This is how you get backlinks and brand awareness for free
- **Open Graph / social preview cards** — when someone shares an AVG game page on Twitter/Reddit/Discord, the preview should show the rank, cover art, and a compelling summary. This drives click-through from social sharing
- **Comparison tool** — "Compare Chrono Trigger vs Final Fantasy VI" side-by-side. Which appears on more lists? Which ranks higher? People love head-to-head comparisons and they're very shareable

---

## 3. Content that brings people back

### Blog / editorial

The blog/articles system already exists. Use it for:
- **Annual "state of the rankings"** posts when lists get updated — what moved up, what's new, what surprises
- **"Most controversial" analysis** — games with the widest spread between their highest and lowest list placements. People will argue about these (and share them)
- **"Underrated/overrated by decade"** — games that appear on many lists but rank lower than expected, or vice versa
- **Platform retrospectives** — "The 50 best PS2 games according to critics" as a proper editorial piece that links to the landing page

### Data exports and embeds

- **Public API** — let people query rankings programmatically. Game databases, YouTube creators making tier lists, Reddit bots that respond with rankings. Every API consumer is a distribution channel
- **CSV/JSON download** — already have CSV download, make sure it's discoverable and includes all the metadata people would want
- **Wikipedia citations** — AVG rankings are more rigorous than Metacritic for all-time lists. Reach out to Wikipedia editors who maintain "best games" lists. If AVG gets cited on Wikipedia, that's massive for authority and backlinks

---

## 4. Community and stickiness

### User features that create habit loops

- **"How acclaimed is your taste?"** — users mark games as played, then see what percentage of the top 100/250/500 they've completed. Shareable result image ("I've played 73% of the top 100 most acclaimed games"). This is the kind of thing that goes viral on Twitter/Reddit
- **Notifications** — "A game you've played just entered the top 100" or "New lists added this month affected these games in your collection"
- **Comments on game pages** — lightweight discussion. "Do you agree with this ranking?" People who comment come back
- **User profiles** — public profile showing played/want-to-play lists. Shareable link

### Newsletter

- Monthly digest: new lists added, biggest ranking changes, new games entering the ranking
- "Your taste report" if they have a played list
- This is the re-engagement channel. Email is the most reliable way to bring people back

---

## 5. Distribution and awareness

### Where to post

- **Reddit** — the r/gaming post already proved this works. Do it again when major updates ship (genre pages, new data, book rankings going live). Also target specific subreddits: r/patientgamers, r/truegaming, r/retrogaming, r/gamedesign, r/indiegaming. Each one cares about a different angle
- **Hacker News** — the methodology/algorithm angle plays well here. A post about "How we rank games using 900+ critic lists" or open-sourcing the algorithm would get traction
- **Game journalist outreach** — when a major game enters the ranking or there's a notable ranking change, email it to game journalists. Make it easy for them to cite AVG
- **YouTube/streaming** — the site is visual and interactive. Reach out to gaming YouTubers who do "ranking" or "tier list" content. Offer them data or a partnership

### SEO-adjacent

- **Google Discover** — editorial content (blog posts, ranking updates) can surface here if the site has good E-E-A-T signals. The methodology page helps establish authority
- **Backlink outreach** — find sites that link to Metacritic's "best of all time" pages and pitch them on linking to AVG instead. AVG's methodology is more rigorous; that's a real selling point
- **Schema markup** — make sure game pages, list pages, and landing pages all have proper structured data so they can appear as rich results in Google

---

## 6. Compete directly with Metacritic/OpenCritic

What AVG does better than Metacritic:
- All-time rankings based on curated critic lists, not averaged review scores
- Match-up algorithm that handles ranked vs. unranked lists, platform-specific lists, one-per-series restrictions
- 900+ lists from 140+ publications vs. Metacritic's simple score averaging

What Metacritic does better:
- Individual game review aggregation (scores for new releases)
- SEO presence (they rank for everything)
- Brand recognition
- New release coverage

### The play

AVG shouldn't try to be Metacritic for new releases. The strength is **all-time acclaim**: which games have stood the test of time according to critics. Own that niche completely.

- Every SEO landing page should have copy that explains why AVG's methodology is better than a simple average score
- The "How It Works" / methodology page should be prominent and well-written — it's the key differentiator
- Consider a "Compare with Metacritic" feature on game pages: "Metacritic score: 92. AVG rank: #47 out of 1,247. Here's why these numbers tell different stories." This positions AVG as the more sophisticated tool
- **"Best games" should autocomplete to AVG** — if we can rank #1 for "best video games of all time," "best [platform] games," and "best [genre] games," we win

---

## Priority order

1. **Platform + genre + decade landing pages** — biggest SEO impact, unblocks organic growth
2. **Open Graph cards + social previews** — makes every share a marketing impression
3. **Structured data / JSON-LD** — helps Google understand and surface the content
4. **"How acclaimed is your taste?" shareable feature** — viral potential, drives signups
5. **Blog content: ranking changes, controversies, retrospectives** — brings people back, builds authority
6. **Embeddable badges** — passive backlink generation
7. **Public API** — long-term distribution channel
8. **Newsletter** — re-engagement
9. **Combo landing pages** — long-tail SEO
10. **Comparison tool** — shareable, differentiated feature
