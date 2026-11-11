---
name: openlibrary
description: Fetch book metadata from Open Library API. Use when asked to search, import, or refresh book data.
---

# Open Library Book Metadata

Import book metadata from Open Library (openlibrary.org), a free digital library with comprehensive book data. No authentication required.

## Basic Usage

```bash
# Search for books by title
python3 manage.py fetch_book_metadata --search "The Great Gatsby"

# Search with author filter
python3 manage.py fetch_book_metadata --search "1984" --author "George Orwell"

# Look up by ISBN
python3 manage.py fetch_book_metadata --isbn "9780743273565"
```

## Command Options

| Option | Description |
|--------|-------------|
| `--search QUERY` | Search for books by title |
| `--author NAME` | Filter search by author name |
| `--isbn ISBN` | Look up book by ISBN |
| `--limit N` | Limit number of results (default: 10) |
| `--source SOURCE` | Data source: `openlibrary`, `hardcover`, or `both` (default: openlibrary) |
| `--output FILE` | Save results to CSV file |
| `--json` | Output results as JSON |

## Examples

```bash
# Search for books and output as JSON
python3 manage.py fetch_book_metadata --search "Lord of the Rings" --json

# Search across both sources (Open Library + Hardcover)
python3 manage.py fetch_book_metadata --search "Dune" --source both

# Export search results to CSV
python3 manage.py fetch_book_metadata --search "Science Fiction" --limit 50 --output books.csv

# Find a specific book by title and author
python3 manage.py fetch_book_metadata --search "Pride and Prejudice" --author "Jane Austen"
```

The command searches and prints (or writes a CSV); it saves nothing to the
database.

## What Open Library Provides

- Book titles and descriptions
- Author information
- Publication year
- ISBN numbers
- Cover images
- Subject/genre classifications
- Page counts

## Data Sources

| Source | Authentication | Coverage |
|--------|---------------|----------|
| Open Library | None (free) | Primary source, comprehensive |
| Hardcover | Optional token | Secondary source, modern books |

## Environment Variables

| Variable | Description |
|----------|-------------|
| `HARDCOVER_API_TOKEN` | Optional Hardcover API token for additional coverage |

## Programmatic Usage

```python
from books import book_metadata

# Create service
service = book_metadata.get_service()

# Get book info
result = service.get_book_info(
    title="The Great Gatsby",
    author="F. Scott Fitzgerald"
)

# Search books
results = service.search_books("dystopian fiction", limit=10)

# ISBN lookup
result = service.get_book_info(title="", isbn="9780743273565")
```

## Result Format

Book metadata is returned in a normalized format:

```python
{
    "title": "The Great Gatsby",
    "authors": ["F. Scott Fitzgerald"],
    "year": 1925,
    "isbn": ["9780743273565"],
    "cover_url": "https://covers.openlibrary.org/b/id/...",
    "genres": ["Classic fiction", "American literature"],
    "description": "A story of decadence and excess...",
    "pages": 180,
    "source": "openlibrary",
    "source_ids": {"work_key": "/works/OL468431W"}
}
```
