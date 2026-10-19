/**
 * Acclaimed Albums - Client-Side Filter Engine
 *
 * Filters and sorts the whole album corpus in the browser, reproducing what
 * `music.views.AlbumHomePageView.get_queryset` does on the server. The two
 * have to agree: the page is server-rendered first and the client takes over
 * from whatever state the URL describes, so a divergence shows up as rows
 * changing under the reader for no reason.
 *
 * Smaller than the games engine: no genre-hierarchy expansion, for the
 * reason `filter()` gives. It does compute facet counts, because the year
 * heatmap and the genre tree the sidebar now shares with the games page
 * expect the number beside each option to answer "how many would this leave
 * me", which changes with every other filter.
 */
class AlbumFilterEngine {
    /**
     * @param {Object} data - The /api/music/all/ payload
     */
    constructor(data) {
        this.albums = data.albums || [];
        this.artists = data.artists || {};
        this.genres = data.genres || [];

        this._genresById = {};
        this.genres.forEach(genre => {
            this._genresById[genre.id] = genre;
        });

        // Each genre's ancestors, so an album tagged "Modern Classical" is
        // counted under "Classical" exactly once - counting a genre and its
        // children separately and adding them up said Classical had two
        // albums when one album carried both names.
        this._ancestorsById = {};
        this.genres.forEach(genre => {
            const chain = [];
            let parent = genre.p;
            while (parent && this._genresById[parent]) {
                chain.push(parent);
                parent = this._genresById[parent].p;
            }
            this._ancestorsById[genre.id] = chain;
        });

        // One haystack per album, built once from exactly the three columns
        // the server's `q` searches - name, name_normalized, artist_credit -
        // lowercased and otherwise untouched. `icontains` is case-insensitive
        // but does not fold accents, so neither does this: folding here would
        // make "Sigur Ros" match a credit the server would not.
        this._haystacks = new Map();
        this.albums.forEach(album => {
            this._haystacks.set(
                album.id,
                [album.n, album.nn, album.c].filter(Boolean).join(' ').toLowerCase()
            );
        });
    }

    /**
     * Add every descendant of the selected genres.
     *
     * The payload gives each genre its descendant ids (`d`), so this is the
     * same expansion `music.views.expand_genre_ids` does server-side.
     * @private
     */
    _expandGenres(genreIds) {
        if (!genreIds.length) return genreIds;
        const expanded = new Set();
        genreIds.forEach(id => {
            expanded.add(Number(id));
            const genre = this._genresById[id];
            (genre && genre.d ? genre.d : []).forEach(child =>
                expanded.add(Number(child))
            );
        });
        return [...expanded];
    }

    /**
     * Facet counts for the sidebar, each dimension counted with its own
     * filter left out.
     *
     * Mirrors `apply_album_filters(..., skip=...)` in music/views.py: the
     * count under a year cell is how many albums that year holds under the
     * *other* filters, so selecting it never gives an empty page.
     *
     * @param {Object} filters
     * @returns {{years: Array<{year: number, count: number}>,
     *            genres: Object<string, number>}}
     */
    facets(filters = {}) {
        // Only the year and genre dimensions are neutralised, so the listen
        // status still applies to both passes - which is what makes a year
        // cell's count agree with what selecting that year would give. The
        // server does the same by not listing `listened` in either `skip`.
        const withoutYears = this.filter(
            Object.assign({}, filters, { start: null, end: null })
        );
        const withoutGenres = this.filter(
            Object.assign({}, filters, { genres: [] })
        );

        const yearCounts = new Map();
        withoutYears.forEach(album => {
            if (album.y === null || album.y === undefined) return;
            yearCounts.set(album.y, (yearCounts.get(album.y) || 0) + 1);
        });

        // Counted per subtree and once per album, as `_genre_counts` does.
        const genreCounts = {};
        withoutGenres.forEach(album => {
            const covered = new Set();
            album.g.forEach(genreId => {
                covered.add(genreId);
                (this._ancestorsById[genreId] || []).forEach(ancestor =>
                    covered.add(ancestor)
                );
            });
            covered.forEach(genreId => {
                genreCounts[genreId] = (genreCounts[genreId] || 0) + 1;
            });
        });

        // Every year in the corpus range, zeros included, as `_year_counts`
        // sends it - so both sides give the same array for the same filter.
        const bounds = this.getYearBounds();
        const years = [];
        for (let year = bounds.min; year <= bounds.max; year++) {
            years.push({ year, count: yearCounts.get(year) || 0 });
        }

        return { years, genres: genreCounts };
    }

    /**
     * Where the matching albums sit across the whole ranking.
     *
     * Mirrors `core.services.ranking.rank_distribution`: bins are built
     * from the global maximum rank, not the filtered one, so the chart's
     * axis does not move when the filters do.
     */
    rankDistribution(albums, binCount = 10) {
        const maxRank = this.albums.reduce(
            (highest, album) => Math.max(highest, album.r || 0),
            0
        );
        if (!maxRank) return [];

        const binSize = Math.ceil(maxRank / binCount);
        const counts = new Array(binCount).fill(0);
        albums.forEach(album => {
            if (!album.r) return;
            const index = Math.floor((album.r - 1) / binSize);
            if (index >= 0 && index < binCount) counts[index] += 1;
        });

        return counts.map((count, index) => ({
            binStart: index * binSize + 1,
            binEnd: Math.min((index + 1) * binSize, maxRank),
            count
        }));
    }

    /**
     * Filter albums.
     *
     * @param {Object} filters
     * @param {string} [filters.q]
     * @param {number} [filters.start] - inclusive release-year floor
     * @param {number} [filters.end] - inclusive release-year ceiling
     * @param {number[]} [filters.artists] - artist ids, OR-ed
     * @param {number[]} [filters.genres] - genre ids, OR-ed
     * @param {string[]} [filters.listened] - 'yes' | 'want' | 'no', OR-ed
     * @returns {Array} Matching albums
     */
    /**
     * Whether an album passes the listen-status filter.
     *
     * Mirrors `music.views._apply_listen_filter`. The state is read from the
     * two global Sets the page renders, not from the album payload: that
     * payload is shared between whoever uses the browser session, so it
     * carries nothing per-user. Games needs a `game.i` guard because an IGDB
     * id may be missing; the album pk is always there.
     *
     * @private
     */
    _passesListenStatus(album, listened) {
        if (!listened || !listened.length || !window.isAuthenticated) return true;

        const done = window.listenedAlbumIds && window.listenedAlbumIds.has(album.id);
        const want =
            window.wantToListenAlbumIds && window.wantToListenAlbumIds.has(album.id);

        return listened.some(status => {
            if (status === 'yes') return Boolean(done);
            if (status === 'want') return Boolean(want);
            if (status === 'no') return !done && !want;
            return false;
        });
    }

    filter(filters = {}) {
        const query = filters.q ? filters.q.trim().toLowerCase() : '';
        const start = Number.isFinite(filters.start) ? filters.start : null;
        const end = Number.isFinite(filters.end) ? filters.end : null;
        const artistIds = filters.artists || [];
        const genreIds = this._expandGenres(filters.genres || []);

        return this.albums.filter(album => {
            if (query && !this._haystacks.get(album.id).includes(query)) {
                return false;
            }

            // A year bound drops albums with no release year, because
            // `year_released__gte` / `__lte` drop NULLs in SQL.
            if (start !== null || end !== null) {
                if (album.y === null || album.y === undefined) return false;
                if (start !== null && album.y < start) return false;
                if (end !== null && album.y > end) return false;
            }

            if (artistIds.length && !artistIds.some(id => album.ar.includes(id))) {
                return false;
            }

            // Genre ids are already expanded to include each selected
            // genre's styles, matching `apply_album_filters` - selecting
            // Rock means rock, not just the albums tagged with the bare
            // word. See `_expandGenres`.
            if (genreIds.length && !genreIds.some(id => album.g.includes(id))) {
                return false;
            }

            if (!this._passesListenStatus(album, filters.listened)) {
                return false;
            }

            return true;
        });
    }

    /**
     * Sort albums in place and return them.
     *
     * Mirrors `music.views.ALBUM_SORTS` and the direction rule in
     * `_apply_sort`: `dir=desc` flips only the primary field, so a tiebreaker
     * keeps pointing the same way - albums by year descending is
     * newest-first then best-ranked, not newest-first then worst-ranked.
     *
     * @param {Array} albums
     * @param {string} sort - 'rank' | 'name' | 'year' | 'lists'
     * @param {string} direction - 'asc' | 'desc'
     * @returns {Array}
     */
    sort(albums, sort = 'rank', direction = 'asc') {
        const descending = direction === 'desc';
        const flip = descending ? -1 : 1;

        const byRank = (a, b) => a.r - b.r;

        const comparators = {
            rank: (a, b) => flip * byRank(a, b),
            // `ni` is the position the server's own `Lower(name)` ordering
            // put this album in, sent with the payload: no JavaScript
            // comparator reproduces a database collation faithfully, so the
            // ordering is taken rather than recomputed.
            name: (a, b) => flip * (a.ni - b.ni),
            // The server's RELEASE_ORDER: the year, then the release date
            // within it, both in the requested direction, then rank.
            year: (a, b) =>
                this._compareYears(a.y, b.y, descending) ||
                this._compareReleaseDates(a.rd, b.rd, descending) ||
                byRank(a, b),
            lists: (a, b) => flip * (a.lc - b.lc) || byRank(a, b)
        };

        const comparator = comparators[sort] || comparators.rank;
        return albums.slice().sort(comparator);
    }

    /**
     * Compare release years in the requested direction, placing nulls the way
     * Postgres does: last when ascending, first when descending. Returns the
     * final ordering, so callers must not flip it again.
     * @private
     */
    _compareYears(left, right, descending) {
        const leftMissing = left === null || left === undefined;
        const rightMissing = right === null || right === undefined;
        if (leftMissing && rightMissing) return 0;
        if (leftMissing) return descending ? -1 : 1;
        if (rightMissing) return descending ? 1 : -1;
        return descending ? right - left : left - right;
    }

    /**
     * Compare ISO release dates in the requested direction. An undated album
     * goes last either way, as the server's `nulls_last=True` puts it.
     * @private
     */
    _compareReleaseDates(left, right, descending) {
        if (!left && !right) return 0;
        if (!left) return 1;
        if (!right) return -1;
        if (left === right) return 0;
        const ascending = left < right ? -1 : 1;
        return descending ? -ascending : ascending;
    }

    /**
     * Filter then sort, as the server's single queryset does.
     * @param {Object} filters - filter keys plus `sort` and `dir`
     * @returns {{albums: Array, total: number}}
     */
    apply(filters = {}) {
        const albums = this.sort(
            this.filter(filters),
            filters.sort || 'rank',
            filters.dir || 'asc'
        );
        return { albums, total: albums.length };
    }

    /**
     * The release-year range across the whole corpus, for the year inputs.
     * @returns {{min: number, max: number}}
     */
    getYearBounds() {
        const years = this.albums
            .map(album => album.y)
            .filter(year => year !== null && year !== undefined);
        if (!years.length) {
            const now = new Date().getFullYear();
            return { min: now, max: now };
        }
        return { min: Math.min(...years), max: Math.max(...years) };
    }

    /**
     * Expand a compact album into what the renderer needs.
     * @param {Object} album
     * @returns {Object}
     */
    expandAlbum(album) {
        return {
            id: album.id,
            name: album.n,
            slug: album.s,
            rank: album.r,
            year: album.y,
            artistCredit: album.c,
            thumbnail: album.t,
            listCount: album.lc,
            artists: (album.ar || [])
                .map(id => this.artists[id])
                .filter(Boolean),
            genres: (album.g || [])
                .map(id => this._genresById[id])
                .filter(Boolean)
        };
    }
}

if (typeof window !== 'undefined') {
    window.AlbumFilterEngine = AlbumFilterEngine;
}
