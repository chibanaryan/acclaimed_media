## Project Overview

Acclaimed Media ranks the most critically acclaimed video games and albums by
aggregating critics' lists. One Django app serves three hosts:
[acclaimedmedia.org](https://acclaimedmedia.org) (a landing page),
[games.acclaimedmedia.org](https://games.acclaimedmedia.org) and
[music.acclaimedmedia.org](https://music.acclaimedmedia.org). It is built with:
- **Django** - Backend framework with server-side rendering
- **HTMX** - Dynamic interactions without full page reloads
- **Alpine.js** - Client-side reactivity for UI components
- **Tailwind CSS v4** - Utility-first CSS framework
- **DaisyUI v5** - Component library for Tailwind

For detailed documentation, see [AGENTS.md](AGENTS.md): the rules, with a
pointer under each heading to the file in [docs/agents/](docs/agents/) that
holds the reasoning and history behind them.

## Setup Local Development Environment

### Prerequisites

- Python, at the release in `.python-version` (3.14)
- Node.js (for Tailwind CSS, minifying JavaScript and the tests that run the
  client code)
- Git
- Heroku CLI

### Clone Repository

```bash
git clone https://github.com/chibanaryan/acclaimed_media.git
cd acclaimed_media
heroku login
heroku git:remote -a acclaimedgames
```

On Windows, enable Developer Mode and clone with
`git clone -c core.symlinks=true ...`. `CLAUDE.md` is a symlink to `AGENTS.md`,
and without that setting it arrives as a one-line text file.

### Install Dependencies

```bash
# Homebrew's Python, at the release in .python-version (see AGENTS.md)
V="$(cat .python-version)"; "$(brew --prefix python@$V)/bin/python$V" -m venv venv

# macOS/Linux:
source venv/bin/activate

# Windows:
venv\Scripts\activate

pip install -r requirements.txt -r requirements-dev.txt
pre-commit install

# Install Tailwind CSS dependencies
python3 manage.py tailwind install
```

### Get Data

**Option A: Sync from Production (Recommended)**

```bash
python3 manage.py sync_from_prod
python3 manage.py createsuperuser
```

**Option B: Start Fresh**

```bash
python3 manage.py migrate
python3 manage.py createsuperuser
```

Then load the checked-in ranking releases, which also fetch the metadata they
need if the credentials in `.env` allow it (`--no-metadata` skips that):

```bash
python3 manage.py import_games_data
python3 manage.py import_music_data
```

### Run Development Server

```bash
DEBUG=True python3 manage.py runserver
```

The host picks the site, as in production:

- `http://games.localhost:8000/` - the game rankings
- `http://music.localhost:8000/` - the album rankings
- `http://localhost:8000/` - the landing page

**Note:** The Tailwind CSS watcher (`python3 manage.py tailwind start`) is only needed if you're actively editing styles. The compiled CSS is committed to git, so for most dev work you just need the Django server.

## Deploy to Production

Deploys go through the `/deploy` skill (`.agent/skills/deploy/SKILL.md`),
which is also the list of steps to follow by hand: build the CSS, minify the
JavaScript, review the change, commit (the hooks run the tests), push to
`main`, wait for CI,
back up the database if migrations ship, push to Heroku and check
`/healthz/`. Heroku runs only the Python buildpack, so the built CSS and the
minified JavaScript are committed.

## CSS Workflow (Tailwind CSS)

The site uses django-tailwind with Tailwind CSS v4 and DaisyUI v5.

**Development:**
- Run `python3 manage.py tailwind start` to watch for changes
- Edit styles in `theme/static_src/src/styles.css`
- CSS automatically rebuilds on save

**Key Files:**
- `theme/static_src/src/styles.css` - Main Tailwind source with custom components
- `theme/static/css/dist/styles.css` - Compiled output (auto-generated)
- `games/static/games/css/mdi-subset.css` - Material Design Icons subset

**Theme Configuration:**
Themes are configured in `styles.css`:
```css
@plugin "daisyui" {
  themes: ["lofi", "forest"];
}
```

lofi is the light theme and forest the dark one; see
[docs/THEME_SYSTEM.md](docs/THEME_SYSTEM.md).

## Pre-commit Hooks

This repo uses [pre-commit](https://pre-commit.com/) to enforce code quality:

- **Black** - Auto-formats Python code
- **Flake8** - Lints for style violations
- **Tests** - Runs the full suite under `pytest`
- **Coverage** - Enforces 100% coverage

Commits are blocked if any check fails. Run tests manually:

```bash
pytest                       # everything, with the coverage gate
pytest games/tests/test_api.py -o addopts=""   # one file, no coverage
```

## Import New Data

The staff `/import/` page on the games site is for loading a **new ranking
release** (not for initial setup - use `sync_from_prod` for that). Music has
its own at `/import/` on the music host, for its four release files.

### Quick Actions

- **Load Test Data** - Load the checked-in release files (the button is shown only under `DEBUG`)
- **Delete Game Data** - Destructive maintenance reset for ranking data
- **Fetch IGDB Data** - Pull cover art, descriptions, and genres

### Batch Import

Upload tab-separated files in order:
1. **PlatformDB.txt** - `CODE<tab>Name`
2. **SourceLists.txt** - `Publisher<tab>Year<tab>Type<tab>Name<tab>URL`
3. **Games file (for example `Top1400.txt`)** - `Rank<tab>Name<tab>Year<tab>Platforms<tab>IGDB_ID<tab>Wikidata_ID`
4. **GamePositions.txt** - `ListID:Position<tab>ListID:Position...`

Regular batch import replaces the existing ranking dataset in place. You do not need to run the delete action first.

### IGDB Import on Heroku

An import fetches the metadata it left missing by itself. To run a pass by
hand (`--` separates Heroku's flags from the command's):

```bash
heroku run -- python manage.py get_igdb
```

## Contributing

Bug reports and data corrections are welcome as issues. Please open an issue
before writing a pull request. See [CONTRIBUTING.md](.github/CONTRIBUTING.md)
and the [Code of Conduct](.github/CODE_OF_CONDUCT.md). Report security problems
privately, as [SECURITY.md](SECURITY.md) describes.

## License

The code is released under the [MIT License](LICENSE). The license does not
cover the ranking data, such as the files in `acclaimedgames/test_input_files/`,
or the metadata the site fetches from IGDB, Wikidata, Discogs, MusicBrainz, the
Cover Art Archive and HowLongToBeat. Those stay under their owners' terms.
