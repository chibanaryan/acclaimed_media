---
name: wikipedia-metadata
description: Fetch Wikipedia and Wikidata metadata for games including page titles, genres, and Wikidata IDs. Use when user asks about Wikipedia data, wiki genres, Wikidata, or metadata refresh. Includes weekly maintenance scheduling.
---

# Wikipedia Metadata Skill

This skill handles fetching game metadata from Wikipedia and Wikidata.

## What It Fetches

- Wikipedia page titles (via Wikidata ID lookup or OpenSearch fallback)
- Primary genre from Wikipedia infobox
- All genres from Wikipedia page
- Wikidata IDs for games

## Primary Command: fetch_wikipedia_metadata

This is the **recommended command** for fetching Wikipedia data. It combines page lookup and genre scraping in one operation.

```bash
# Fetch for all games needing data (recommended)
python3 manage.py fetch_wikipedia_metadata --save --skip-existing

# Force refresh all games
python3 manage.py fetch_wikipedia_metadata --save --force

# Process with limit (for testing)
python3 manage.py fetch_wikipedia_metadata --save --limit 100

# Process single game
python3 manage.py fetch_wikipedia_metadata --game "The Legend of Zelda" --save
```

### How It Works

1. Looks up Wikipedia page titles using Wikidata IDs (fast)
2. Falls back to OpenSearch API if Wikidata lookup fails
3. Scrapes genre data from Wikipedia pages

### Data Storage

- Page titles → `WikipediaGameData` records
- Genres → `WikipediaGenre` objects
- Wikidata IDs → `Game.wikidata_id` field

## Standalone Genre Command: get_wiki_genres

Use this only if you need genre data without page titles.

```bash
# Process all games (outputs CSV)
python3 manage.py get_wiki_genres

# Save to database
python3 manage.py get_wiki_genres --save

# Single game test
python3 manage.py get_wiki_genres --game "The Legend of Zelda"

# Skip existing
python3 manage.py get_wiki_genres --skip-existing --save
```

Uses cascade approach: Wikidata P136 property → Wikipedia infobox scraping.

## Weekly Metadata Refresh

For scheduled maintenance, use the unified refresh command:

```bash
# Full refresh (IGDB + Wikipedia)
python3 manage.py refresh_all_metadata

# Wikipedia only
python3 manage.py refresh_all_metadata --wikipedia-only

# IGDB only
python3 manage.py refresh_all_metadata --igdb-only

# Dry-run preview
python3 manage.py refresh_all_metadata --dry-run

# With limit (testing)
python3 manage.py refresh_all_metadata --limit 100
```

### Performance

| Operation | Duration |
|-----------|----------|
| Full refresh | ~40 minutes (3000+ games) |
| Wikipedia only | ~38 minutes |
| IGDB only (free) | ~30 seconds |
| IGDB only (pro) | ~3 seconds |

### Heroku Scheduler Setup

```bash
# Add scheduler add-on
heroku addons:create scheduler:standard

# Configure in Heroku Dashboard:
# Command: python3 manage.py refresh_all_metadata
# Schedule: Weekly (Sunday 2:00 AM UTC)
# Dyno: Performance-M (for 40-minute job)
```

## Environment Variables

```
WIKIDATA_ACCESS_TOKEN=your_token  # Highly recommended (2.5x faster)
```

## Command Options Reference

### fetch_wikipedia_metadata
| Option | Description |
|--------|-------------|
| `--save` | Save results to database |
| `--skip-existing` | Skip games with existing data |
| `--force` | Force refresh all games |
| `--limit N` | Process only N games |
| `--game "Name"` | Process single game |

### refresh_all_metadata
| Option | Description |
|--------|-------------|
| `--igdb-only` | Skip Wikipedia |
| `--wikipedia-only` | Skip IGDB |
| `--limit N` | Process only N games |
| `--dry-run` | Preview without changes |
| `--concurrency N` | IGDB concurrency |
| `--pro` | Use IGDB Pro tier |
