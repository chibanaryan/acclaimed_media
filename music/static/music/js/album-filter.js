/**
 * Acclaimed Albums - Client-Side Filter Engine
 *
 * Filters and sorts the whole album corpus in the browser, reproducing what
 * `music.views.AlbumHomePageView.get_queryset` does on the server. The two
 * have to agree: the page is server-rendered first and the client takes over
 * from whatever state the URL describes, so a divergence shows up as rows
 * changing under the reader for no reason.
 *
 * Deliberately smaller than the games and books engines: there are no facet
 * counts to compute (the counts beside the filter options are all-time
 * figures the server renders once) and no genre-hierarchy expansion - see
 * `filter()`.
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
     * Filter albums.
     *
     * @param {Object} filters
     * @param {string} [filters.q]
     * @param {number} [filters.start] - inclusive release-year floor
     * @param {number} [filters.end] - inclusive release-year ceiling
     * @param {number[]} [filters.artists] - artist ids, OR-ed
     * @param {number[]} [filters.genres] - genre ids, OR-ed
     * @returns {Array} Matching albums
     */
    filter(filters = {}) {
        const query = filters.q ? filters.q.trim().toLowerCase() : '';
        const start = Number.isFinite(filters.start) ? filters.start : null;
        const end = Number.isFinite(filters.end) ? filters.end : null;
        const artistIds = filters.artists || [];
        const genreIds = filters.genres || [];

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

            // Flat id matching, no walk down the tree. The server filters
            // `genres__id__in` without expanding descendants, so selecting a
            // root genre matches only albums tagged with the root itself -
            // which is also what the all-time count beside that option
            // reports. Expanding here would disagree with both.
            if (genreIds.length && !genreIds.some(id => album.g.includes(id))) {
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
            year: (a, b) =>
                this._compareYears(a.y, b.y, descending) || byRank(a, b),
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
