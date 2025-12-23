---
name: igdb-import
description: Import and manage IGDB (Internet Game Database) data for games. Use when user asks about IGDB, importing game data, fetching cover art, game descriptions, or developer information from IGDB. Includes performance tuning and Pro tier options.
---

# IGDB Import Skill

This skill handles importing game data from the IGDB (Internet Game Database) API.

## What IGDB Provides

- Cover art images
- Game descriptions
- Developer/studio information
- Genre classifications
- Platform data

## Basic Commands

```bash
# Default import (maximum throughput)
# Free tier: batch=50, concurrency=8
python3 manage.py get_igdb

# Import specific game
python3 manage.py get_igdb --game "The Legend of Zelda"
python3 manage.py get_igdb --slug "legend-of-zelda"
python3 manage.py get_igdb --id 123

# Force refresh existing data
python3 manage.py get_igdb --force
```

## Performance Tuning

### Command Options

| Option | Description | Default |
|--------|-------------|---------|
| `--concurrency N` | Concurrent requests (1-8) | 8 |
| `--batch-games N` | Games per API request (0-500) | 50 (free) / 500 (pro) |
| `--delay SECONDS` | Delay between games | 0.0 |
| `--batch-size N` | Progress checkpoint interval | 50 |
| `--pro` | Use Pro tier | False |

### Performance Presets

```bash
# Conservative mode (slower but safer)
python3 manage.py get_igdb --concurrency 4 --batch-games 20

# Sequential mode (disable optimizations)
python3 manage.py get_igdb --concurrency 1 --batch-games 0

# Pro tier (requires subscription)
python3 manage.py get_igdb --pro
```

### Expected Performance

| Mode | Speed | Games/Min |
|------|-------|-----------|
| Free tier defaults | ~100 games/sec | 6,000 |
| Sequential mode | ~2 games/sec | 120 |
| Pro tier | ~1000+ games/sec | 60,000+ |

**Time estimates for 1000 games:**
- Free tier: ~10 seconds
- Pro tier: ~1 second

## Environment Variables

Required in `.env`:
```
IGDB_CLIENT_ID=your_client_id
IGDB_CLIENT_SECRET=your_client_secret
IGDB_USE_PRO_TIER=True  # Optional, enables Pro tier
```

## Technical Details

The `games/igdb.py` module uses these optimization strategies:

1. **Field Expansion** - Reduces API calls 3-5x by expanding cover/genre data in main query
2. **Concurrent Requests** - Up to 8 simultaneous requests for 4-8x speedup
3. **Multi-Query Batching** - Multiple games per request for additional 3-5x speedup
4. **Thread-Safe** - All caching and rate limiting is thread-safe

## Programmatic Usage

```python
# Fetch IGDB data for a single game
game = Game.objects.get(slug="zelda")
game.get_igdb_data()
```
