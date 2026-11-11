/**
 * Acclaimed Albums - Client-Side Filtering Integration
 *
 * Takes over the album rankings page's filter form once the whole corpus is
 * in the browser: 1000 albums, about 95 KB gzipped, so filtering a 100-row
 * page costs nothing locally where every change was an HTMX round trip.
 *
 * Progressive enhancement, deliberately. The page is server-rendered and its
 * HTMX form filters server-side on its own; this file suppresses those
 * requests only once it has data and a renderer, so a slow or failed bundle
 * leaves a page that still works. There is no Alpine component and no
 * IndexedDB layer: the sidebar is a plain GET form whose fields are already
 * the engine's inputs, and the payload is small enough to refetch per
 * session.
 */
class AlbumClientSideFiltering {
    constructor() {
        this.engine = null;
        this.renderer = null;
        this.isInitialized = false;
        this.initPromise = null;
        this.currentFilters = {};
        this.viewMode = 'list';
        this.form = null;
        // Where the server's rows start: 0, or a `?page=N` link's offset,
        // until the renderer adopts them or the engine renders its own
        this.pageStart = 0;
        // The version of the data it loaded (followsPage)
        this.dataVersion = null;
        // Set once its data has failed to load, for good: the page stays
        // HTMX's, and mediaListControls rolls a failed request back itself
        this.failed = false;
    }

    /**
     * Adopt the sidebar form and the state the server rendered with.
     *
     * Nothing is re-rendered on load - the server already rendered this
     * filter state - so without this the instance would hold no filters at
     * all, and the first Load More or view switch would read fields off
     * nothing.
     */
    attach(form) {
        this.form = form;
        this.currentFilters = this.readFilters(form);
        this.pageStart = serverPageStart();
    }

    /**
     * Point the renderer at the current result set without re-rendering.
     *
     * Load More and jump-to-rank continue a list the server rendered, so the
     * renderer has to know what the whole list is and how much of it is
     * already on the page before it can append the next slice.
     * @private
     */
    _syncRendererWithPage() {
        if (!this.isInitialized) return;
        if (this.renderer.currentItems && this.renderer.currentItems.length) return;

        const filters = this.form ? this.readFilters(this.form) : this.currentFilters;
        this.currentFilters = filters;
        const { albums } = this.engine.apply(filters);
        this.renderer.adopt(albums, loadedAlbumCount(), this.pageStart);
        this.pageStart = 0;
        this.renderer._currentViewMode = this.viewMode;
        this.renderer._currentShowRank = this._isFiltered(filters)
            ? 'filtered'
            : 'alltime';
    }

    /**
     * Re-announce the year and genre counts for the form's current state.
     *
     * For sidebar components created after the last update - the mobile
     * sheet builds its filters on first open, and a desktop sidebar skipped
     * on a narrow first load is initialised when the window widens - which
     * would otherwise show the counts they were rendered with.
     * @returns {boolean} Whether there was an engine to count with
     */
    republishFacets() {
        if (!this.isInitialized) return false;
        const filters = this.form ? this.readFilters(this.form) : this.currentFilters;
        this._dispatchFacetCounts(this.engine.facets(filters));
        return true;
    }

    /** Announce year and genre counts to the sidebar's components. @private */
    _dispatchFacetCounts(facets) {
        window.dispatchEvent(
            new CustomEvent('year-counts-update', { detail: facets.years })
        );
        window.dispatchEvent(
            new CustomEvent('genre-counts-update', { detail: facets.genres })
        );
    }

    /** Whether the engine and renderer are ready to take the page over. */
    isReady() {
        return this.isInitialized;
    }

    /** Switch between list and grid, re-rendering if we own the list. */
    setViewMode(mode) {
        this.viewMode = mode === 'grid' ? 'grid' : 'list';
        if (!this.isInitialized) return;

        if (this.renderer.currentItems && this.renderer.currentItems.length) {
            this.applyFilters(this.currentFilters);
        } else {
            // Still showing the server's rows and cards, which the view
            // class switches between on its own.
            this.renderer._currentViewMode = this.viewMode;
        }
    }

    /** The sessionStorage key, versioned so stale data is never read. */
    static storageKey(version) {
        return `albumData:${version}`;
    }

    /**
     * The view the list/grid toggle was last left in. The same key
     * core/js/media-list-controls.js writes.
     * @private
     */
    _storedViewMode() {
        try {
            return localStorage.getItem('albumViewMode') === 'grid'
                ? 'grid'
                : 'list';
        } catch (e) {
            return 'list';
        }
    }

    /**
     * Load the bulk payload: this session's copy if it matches the version
     * the page was rendered with, otherwise the network.
     *
     * sessionStorage rather than IndexedDB or localStorage: a tab-scoped copy
     * is the shortest lifetime that still avoids refetching on every
     * navigation.
     * @private
     */
    async _loadData() {
        const version = window.albumDataVersion || '';
        const key = AlbumClientSideFiltering.storageKey(version);

        if (version) {
            try {
                const stored = sessionStorage.getItem(key);
                if (stored) {
                    const data = JSON.parse(stored);
                    this.dataVersion = data.version;
                    return data;
                }
            } catch (e) {
                // Private mode, blocked storage, or a truncated entry.
            }
        }

        const response = await fetch(window.albumDataUrl || '/api/all/', {
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
            credentials: 'same-origin'
        });
        if (!response.ok) {
            throw new Error(`album data request failed: ${response.status}`);
        }
        const data = await response.json();

        if (version && data.version === version) {
            try {
                sessionStorage.setItem(key, JSON.stringify(data));
            } catch (e) {
                // Over quota: filtering still works, it just refetches.
            }
        }
        // Kept, since data of another version cannot continue the page's
        // rows (followsPage)
        this.dataVersion = data.version;
        return data;
    }

    /**
     * Whether the data is the version the page was rendered from. The
     * renderer continues the page's rows by position, so data of another
     * version - an import committed between the page and its payload - has
     * to render the list itself rather than take it over
     * @returns {boolean}
     */
    followsPage() {
        return Boolean(this.dataVersion) &&
            this.dataVersion === (window.albumDataVersion || '');
    }

    /**
     * Fetch the data and build the engine and renderer.
     * @returns {Promise<boolean>} Whether client-side filtering is usable
     */
    async init() {
        if (this.isInitialized) return true;
        if (this.initPromise) return this.initPromise;

        this.initPromise = (async () => {
            try {
                const data = await this._loadData();
                this.engine = new AlbumFilterEngine(data);
                this.renderer = new AlbumListRenderer(this.engine);
                this.viewMode = this._storedViewMode();
                this.isInitialized = true;
                return true;
            } catch (e) {
                console.warn('[albums] client-side filtering unavailable:', e);
                return false;
            }
        })();

        return this.initPromise;
    }

    /**
     * Read the current filter state off the sidebar form.
     *
     * Through FormData so that the client and the server read one
     * vocabulary: these are the same field names `AlbumHomePageView` parses.
     * @param {HTMLFormElement} form
     * @returns {Object}
     */
    readFilters(form) {
        const data = new FormData(form);
        return AlbumClientSideFiltering.parseFilters(name => data.get(name));
    }

    /**
     * The filter state the server rendered the list with, in readFilters'
     * shape, or null if the page carries none. Not the URL's: the server
     * echoes `?artists=Prince` as `prince`, and a repeated parameter as its
     * last value, which the form's fields were rendered from too. Only an
     * htmx swap rewrites it, so it describes the list only until the engine
     * first renders: the takeover is its one reader.
     * @returns {?Object}
     */
    renderedFilters() {
        const rendered = document.getElementById('album-rendered-filters');
        if (!rendered) return null;
        return AlbumClientSideFiltering.parseFilters(name => rendered.dataset[name]);
    }

    /**
     * The filter state from a field reader, one rule for the form and the
     * server's record of what it rendered. Static, as readFilters needs no
     * instance: core/tests/js/filter_parity.js calls it unbound.
     * @param {function(string): ?string} get
     * @returns {Object}
     */
    static parseFilters(get) {
        const text = name => (get(name) || '').toString().trim();
        const number = name => {
            const parsed = parseInt(text(name), 10);
            return Number.isFinite(parsed) ? parsed : undefined;
        };
        const ids = name =>
            text(name)
                .split(',')
                .map(part => parseInt(part.trim(), 10))
                .filter(Number.isFinite);

        // The status values are words, not ids, so they get their own
        // reader rather than going through `ids`.
        const words = name =>
            text(name)
                .split(',')
                .map(part => part.trim())
                .filter(Boolean);

        return {
            q: text('q'),
            start: number('start'),
            end: number('end'),
            // Slugs: the page never carries an artist pk.
            artists: words('artists'),
            genres: ids('genres'),
            listened: words('listened'),
            sort: text('sort') || 'rank',
            dir: text('dir') || 'asc'
        };
    }

    /**
     * Whether any filter is set, which is what decides between showing
     * all-time ranks and positions within the filtered set. Mirrors
     * `is_filtered` in the view: sort and direction do not count.
     * @private
     */
    _isFiltered(filters) {
        const current = filters || {};
        return Boolean(
            current.q ||
            current.start !== undefined ||
            current.end !== undefined ||
            (current.artists && current.artists.length) ||
            (current.genres && current.genres.length) ||
            (current.listened && current.listened.length)
        );
    }

    /**
     * Filter, render, and update the count and the load-more button.
     * @param {Object} filters
     * @param {Object} [options]
     * @param {number} [options.highlightId]
     * @param {number[]} [options.range] - [start, end) to render in place of
     *     the first page: the rows a page had, when its data has moved on
     */
    applyFilters(filters, options = {}) {
        if (!this.isInitialized) return;

        this.currentFilters = filters;
        // The engine's rows start at the top, whatever page the server's did
        this.pageStart = 0;
        const { albums } = this.engine.apply(filters);
        const showRank = this._isFiltered(filters) ? 'filtered' : 'alltime';

        const container = document.getElementById('album-list-container');
        if (!container) return;

        this.renderer.reset();
        // A range past the end, after an import shortened the list, is the
        // top of it, where an empty result says so
        if (options.range && options.range[0] < albums.length) {
            // From an empty window, so the range replaces the page's rows
            // rather than growing them
            this.renderer.currentItems = albums;
            this.renderer._currentShowRank = showRank;
            const [start, end] = options.range.map(at => Math.min(at, albums.length));
            this.renderer.showRange(container, start, end, {
                showRank,
                viewMode: this.viewMode
            });
        } else {
            this.renderer.render(albums, container, {
                showRank,
                highlightId: options.highlightId || null,
                viewMode: this.viewMode
            });
        }

        this._updatePaging();
        this._publishFacets(filters, albums);
    }

    /**
     * Take an album out of the list once a status change has left it outside
     * the filters, without moving the reader.
     *
     * Re-rendering from the top, as a filter change does, put a reader who
     * had loaded down to row 300 back at row 1. Instead its row and card
     * come off the page and the positions after them move up one, with
     * nothing re-rendered, so a quick-mark click costs the same at row 900
     * as at row 1. Read fresh each time from the engine and the page,
     * whichever of the server or the engine drew the rows.
     * @param {Object} filters
     * @param {number} albumId
     */
    dropIfFilteredOut(filters, albumId) {
        if (!this.isInitialized) return;
        const container = document.getElementById('album-list-container');
        if (!container) return;

        const { albums } = this.engine.apply(filters);
        // Still in, under another status the filter also takes
        if (albums.some(album => album.id === albumId)) return;

        this.currentFilters = filters;
        const synced = this.renderer.currentItems && this.renderer.currentItems.length;
        const removed = this.renderer.removeItem(container, albumId, this._showRank());
        if (!loadedAlbumCount()) {
            // Nothing left on the page: start the list again, or say it is empty
            this.applyFilters(filters);
            return;
        }

        if (synced) {
            this.renderer.currentItems = albums;
            if (removed) this.renderer.windowEnd -= 1;
        } else {
            this._syncRendererWithPage();
        }
        this._updatePaging();
        this._publishFacets(filters, albums);
    }

    /**
     * Redraw everything that describes the renderer's window: both
     * result-count lines (the controls partial renders one for desktop and a
     * compact one for mobile), Load Previous, and Load More.
     * @private
     */
    _updatePaging() {
        const state = this.renderer.windowState();

        document.querySelectorAll(
            '#album-results-container [data-result-count]'
        ).forEach(line => {
            line.innerHTML = this.renderer.getResultSummaryHtml(state.loaded, state.total, {
                start: state.start,
                compact: line.dataset.resultCount === 'mobile'
            });
        });

        const previous = document.querySelector(
            '#album-results-container .load-previous-container'
        );
        if (previous) {
            previous.innerHTML = this.renderer.getLoadPreviousHtml(state);
        }

        this._updateLoadMore(state);
    }

    /**
     * Re-publish the sidebar's facet counts from the engine.
     *
     * The server sends these with each render; once filtering happens in the
     * browser nothing asks the server again, so the year grid and the genre
     * tree would keep showing the counts from the last page load.
     * @private
     */
    _publishFacets(filters, albums) {
        this._dispatchFacetCounts(this.engine.facets(filters));
        window.dispatchEvent(
            new CustomEvent('rank-distribution-update', {
                detail: this.engine.rankDistribution(albums)
            })
        );
    }

    /**
     * Replace the server's HTMX load-more button with one this class drives.
     * @private
     */
    _updateLoadMore(state) {
        const existing = document.querySelector(
            '#album-results-container .load-more-container'
        );

        // Nothing under an empty result's message; otherwise the button, or
        // the "all loaded" note, as the server renders one or the other
        const html = this.renderer.getLoadMoreHtml(state);
        if (!html) {
            if (existing) existing.remove();
            return;
        }

        const container = existing || document.createElement('div');
        container.id = 'load-more-container';
        container.className = 'load-more-container text-center my-6';
        container.innerHTML = html;
        if (!existing) {
            document.getElementById('album-results-container').appendChild(container);
        }
    }

    /** The rank column to show for the current filters. @private */
    _showRank() {
        return this._isFiltered(this.currentFilters) ? 'filtered' : 'alltime';
    }

    /** How many albums the current filters match. */
    matchCount() {
        if (!this.isInitialized) return 0;
        this._syncRendererWithPage();
        return this.renderer.currentItems.length;
    }

    /** Append the next page and refresh the count and buttons. */
    loadMore() {
        const container = document.getElementById('album-list-container');
        if (!container || !this.isInitialized) return;

        this._syncRendererWithPage();
        this.renderer.loadMore(container, { showRank: this._showRank() });
        this._updatePaging();
    }

    /**
     * Prepend the page above a jumped-to window, keeping the reader on the
     * row they were looking at.
     */
    loadPrevious() {
        const container = document.getElementById('album-list-container');
        if (!container || !this.isInitialized) return;

        this._syncRendererWithPage();
        const restoreScroll = this.renderer.captureScrollAnchor(container);
        this.renderer.loadPrevious(container, { showRank: this._showRank() });
        // The button can disappear as well, so keep the place after both
        this._updatePaging();
        restoreScroll();
    }

    /**
     * Bring `position` (1-based, in the current result set) onto the page.
     *
     * Only the target and JUMP_RADIUS rows either side are rendered, not
     * everything above it; one already on the page is left as it is, and one
     * near the rendered rows extends them. See BaseMediaListRenderer.planJump.
     * @param {number} position
     */
    jumpTo(position) {
        const container = document.getElementById('album-list-container');
        if (!container || !this.isInitialized) return;

        this._syncRendererWithPage();
        const plan = this.renderer.planJump(position - 1);
        if (plan.mode === 'scroll') return;

        this.renderer.showRange(container, plan.start, plan.end, {
            showRank: this._showRank(),
            viewMode: this.viewMode
        });
        this._updatePaging();
    }

    /**
     * Mirror the filter state into the URL, as `hx-push-url` did.
     * @private
     */
    pushUrl(filters, { replace = false } = {}) {
        const params = new URLSearchParams();
        if (filters.q) params.set('q', filters.q);
        if (filters.start !== undefined) params.set('start', filters.start);
        if (filters.end !== undefined) params.set('end', filters.end);
        if (filters.artists.length) params.set('artists', filters.artists.join(','));
        if (filters.genres.length) params.set('genres', filters.genres.join(','));
        if (filters.listened.length) {
            params.set('listened', filters.listened.join(','));
        }
        if (filters.sort && filters.sort !== 'rank') params.set('sort', filters.sort);
        if (filters.dir && filters.dir !== 'asc') params.set('dir', filters.dir);

        // Always onto the rankings URL, never relative to the current path:
        // on a landing page such as /genres/rock/, a relative push
        // kept the path - and with it the path's own genre - so clearing
        // the genre and reloading brought rock straight back.
        const query = params.toString();
        const base = window.albumRankingsUrl || window.location.pathname;
        const url = query ? `${base}?${query}` : base;
        // Already there: a submit, or a commit that changed nothing the URL
        // spells, would otherwise leave a second entry for Back to step over.
        if (url === window.location.pathname + window.location.search) return;
        window.history[replace ? 'replaceState' : 'pushState']({}, '', url);
    }
}

/**
 * Scroll to the Nth row currently on the page and flash it.
 *
 * Positional, like the games page's equivalent: the box takes a position in
 * the current result set, which is only the album's own rank when nothing is
 * filtered.
 */
function scrollToAlbumPosition(position) {
    const container = document.getElementById('album-list-container');
    const isGrid = container && container.classList.contains('view-grid');
    // After a jump the first rendered row is at windowStart, not the top.
    // Only ever called after jumpTo(), so the renderer holds the result set.
    const offset = getAlbumClientSideFiltering().renderer.windowStart;
    const index = position - 1 - offset;

    let target = null;
    const highlight = [];

    if (isGrid) {
        const card = document.querySelectorAll('.media-card-grid')[index];
        if (card) {
            target = card;
            highlight.push(card);
        }
    } else {
        const desktop = document.querySelectorAll('.media-row.desktop')[index];
        const mobile = document.querySelectorAll('.media-row.media-card-mobile')[index];
        // Each half is display:none at the other's breakpoint, so the one
        // with a layout box is the one the reader can see.
        target =
            (desktop && desktop.offsetParent !== null && desktop) ||
            (mobile && mobile.offsetParent !== null && mobile) ||
            desktop ||
            mobile ||
            null;
        if (desktop) highlight.push(desktop);
        if (mobile) highlight.push(mobile);
    }

    if (!target) return;

    flashHighlight(target, highlight);
}

/**
 * Scroll to an album's row or card by id and flash it.
 *
 * What a `?highlight=` link from album detail lands on, as the games
 * rankings page does: the highlight fades after a couple of seconds, or as
 * soon as the reader hovers another row.
 * @param {number} albumId
 * @param {string} [viewMode] - see albumViewIsGrid
 * @param {Object} [options]
 * @param {boolean} [options.scroll=true] - false flashes it where it is
 * @returns {boolean} Whether the album is on the page
 */
function scrollToAlbumById(albumId, viewMode, { scroll = true } = {}) {
    const isGrid = albumViewIsGrid(viewMode);

    let target = null;
    const highlight = [];

    if (isGrid) {
        const card = document.getElementById(`music-${albumId}-grid`);
        if (card) {
            target = card;
            highlight.push(card);
        }
    } else {
        const desktop = document.getElementById(`music-${albumId}`);
        const mobile = document.getElementById(`music-${albumId}-mobile`);
        // As in scrollToAlbumPosition: the half with a layout box is the
        // one the reader can see.
        target =
            (desktop && desktop.offsetParent !== null && desktop) ||
            (mobile && mobile.offsetParent !== null && mobile) ||
            desktop ||
            mobile ||
            null;
        if (desktop) highlight.push(desktop);
        if (mobile) highlight.push(mobile);
    }

    if (!target) return false;

    flashHighlight(scroll ? target : null, highlight);
    return true;
}

/**
 * Whether one of an album's rows, or its card, has its middle on screen: a
 * sliver under the sticky header is a row scrolled past.
 * @param {number} albumId
 * @returns {boolean}
 */
function albumInView(albumId) {
    return ['', '-mobile', '-grid'].some(suffix => {
        const element = document.getElementById(`music-${albumId}${suffix}`);
        if (!element || element.offsetParent === null) return false;
        const box = element.getBoundingClientRect();
        const middle = (box.top + box.bottom) / 2;
        return middle > 0 && middle < window.innerHeight;
    });
}

/**
 * Whether the list is in grid view: `viewMode` if given, otherwise the
 * container's class. The class is Alpine's `:class`, which on a fresh load
 * may not be applied yet when the engine is ready, so a caller that knows
 * the mode passes it.
 */
function albumViewIsGrid(viewMode) {
    if (viewMode) return viewMode === 'grid';
    const container = document.getElementById('album-list-container');
    return Boolean(container && container.classList.contains('view-grid'));
}

/**
 * The index of the first row the server rendered: 0, or a later page's start
 * for a `?page=N` link. Read once, as the engine takes over: its own renders
 * replace the rows under the same container, which would keep the attribute.
 */
function serverPageStart() {
    const container = document.getElementById('album-list-container');
    if (!container || !container.dataset.windowStart) return 0;
    const start = parseInt(container.dataset.windowStart, 10) || 0;
    delete container.dataset.windowStart;
    return start;
}

/** How many rows are on the page now, in whichever view is showing. */
function loadedAlbumCount() {
    const container = document.getElementById('album-list-container');
    if (!container) return 0;
    const selector = albumViewIsGrid()
        ? '.media-card-grid'
        : '.media-row.desktop';
    return container.querySelectorAll(selector).length;
}

/**
 * Wire the jump-to-rank boxes in the results header, and switch them on.
 *
 * The controls partial renders a pair of them, one for each breakpoint, so
 * the handlers are delegated from the document rather than bound per input.
 */
function initAlbumJumpToRank(csf) {
    // Rendered disabled (`jump_awaits_engine`), because only the engine can
    // answer them: without its data the box took a number and ignored Enter.
    document.querySelectorAll('[data-awaits-engine]').forEach(control => {
        control.disabled = false;
    });

    const jump = input => {
        const target = parseInt(input.value, 10);
        if (!Number.isFinite(target) || target < 1 || target > csf.matchCount()) {
            input.classList.add('input-error');
            setTimeout(() => input.classList.remove('input-error'), 1000);
            return;
        }

        csf.jumpTo(target);
        scrollToAlbumPosition(target);
        input.value = '';
    };

    document.addEventListener('click', event => {
        const button = event.target.closest('.jump-to-rank-btn');
        if (!button) return;
        const input = button
            .closest('div')
            .querySelector('.jump-to-rank-input');
        if (input) jump(input);
    });

    document.addEventListener('keydown', event => {
        if (event.key !== 'Enter') return;
        if (!event.target.classList.contains('jump-to-rank-input')) return;
        event.preventDefault();
        jump(event.target);
    });
}

let _albumClientSideFiltering = null;

/** The page's single instance. */
function getAlbumClientSideFiltering() {
    if (!_albumClientSideFiltering) {
        _albumClientSideFiltering = new AlbumClientSideFiltering();
    }
    return _albumClientSideFiltering;
}

/**
 * Wire the sidebar up to the client-side engine.
 *
 * Until `init()` resolves, nothing is intercepted and HTMX keeps serving
 * filter changes from the server. From then on every request the sidebar
 * would make is suppressed - the form, the decade chips and the load-more
 * button alike. Leaving any of them to HTMX would let a server-rendered swap
 * interleave with client-rendered rows.
 */
function initAlbumFiltering() {
    const form = document.getElementById('album-filters');
    const results = document.getElementById('album-results-container');
    if (!form || !results) return;

    const csf = getAlbumClientSideFiltering();
    let ready = false;

    // Stop the server round-trip for anything the engine can answer itself,
    // once it can. Only GETs: these listeners sit on the form and on the
    // results container, so every HTMX request raised by anything *inside*
    // the results bubbles through them - including a row's listen-status
    // POST, which has to reach the server and which cancelling here would
    // silently swallow the moment the bundle finished loading.
    const suppressHtmx = event => {
        if (!ready) return;
        const detail = event.detail || {};
        const verb = (detail.requestConfig && detail.requestConfig.verb) || 'get';
        if (verb.toLowerCase() !== 'get') return;
        event.preventDefault();
    };
    form.addEventListener('htmx:beforeRequest', suppressHtmx);
    results.addEventListener('htmx:beforeRequest', suppressHtmx);

    // The filter and Load More requests the server is still answering when
    // the engine takes over, which the takeover below aborts and answers
    // itself. Read from htmx's own events, not the spinner's htmx-request
    // class, which moving the spinner would silently stop finding; and only
    // those two, so a row's listen-status POST is never aborted. beforeSend,
    // because it fires only for a request that is really going out. Keyed on
    // the xhr: when the asker has been swapped out, htmx re-fires
    // afterRequest on an ancestor as its `elt`.
    const pending = new Map();
    // The parameters of the form's last request if it failed, which leaves
    // the form ahead of the list just as one still in flight does
    let failedParams = null;
    const track = event => {
        const asker = event.detail.elt;
        if (asker !== form && !asker.matches('.load-more-button')) return;
        pending.set(event.detail.xhr, asker);
    };
    const untrack = event => {
        if (pending.get(event.detail.xhr) === form) {
            const config = event.detail.requestConfig;
            failedParams = event.detail.successful ? null : (config && config.parameters) || {};
            // For controls Alpine starts after the engine has failed
            csf.failedParams = failedParams;
        }
        pending.delete(event.detail.xhr);
    };
    const tracking = on => [form, results].forEach(element => {
        const method = on ? 'addEventListener' : 'removeEventListener';
        element[method]('htmx:beforeSend', track);
        element[method]('htmx:afterRequest', untrack);
    });
    tracking(true);

    const currentHighlight = () => {
        const highlight = new URLSearchParams(window.location.search).get('highlight');
        const parsed = parseInt(highlight, 10);
        return Number.isFinite(parsed) ? parsed : null;
    };

    const rerender = ({ push = true, highlightId = null, replace = false } = {}) => {
        const filters = csf.readFilters(form);
        csf.applyFilters(filters, { highlightId });
        if (push) csf.pushUrl(filters, { replace });
    };

    // A genre clicked in a row filters by it, as it does on the games
    // rankings page. Bound before init resolves so the click works either
    // way: the select is the filter's single source of truth, and a change
    // with a detail is what both HTMX and the engine below listen for.
    document.addEventListener('add-genre', event => {
        const select = form.querySelector('[name="genres"]');
        const genreId = event.detail && event.detail.genreId;
        if (!select || !genreId) return;
        select.value = String(genreId);
        // `filters` lives on the Alpine controls component, and the heading
        // and the sidebar's genre tree are both built from it. Setting the
        // select alone left them showing the previous selection.
        window.dispatchEvent(new CustomEvent('genres-selected', {
            detail: { genres: [String(genreId)] },
        }));

        if (!ready) {
            select.dispatchEvent(new CustomEvent('change', { bubbles: true, detail: {} }));
            return;
        }
        const highlight = parseInt(event.detail.itemId, 10);
        rerender({ highlightId: Number.isFinite(highlight) ? highlight : null });
    });

    // A toggle can change whether a row still belongs in the results.
    // media-tracking.js has already updated the Sets the engine reads by the
    // time this fires, so re-filtering is all that is needed.
    window.addEventListener('album-status-changed', event => {
        if (!ready) return;
        const filters = csf.readFilters(form);
        if (!filters.listened.length) return;
        const albumId = parseInt(event.detail && event.detail.id, 10);
        if (!Number.isFinite(albumId)) return;
        csf.dropIfFilteredOut(filters, albumId);
    });

    // A `?highlight=` link from album detail lands on the album, as it does
    // on the games rankings page. If the server rendered its row, scroll now
    // - after a beat, so Alpine has laid out the heading and sidebar above
    // it - without waiting on the data. Otherwise it is further down the
    // result set, and finding it waits for the engine below.
    const highlightOnLoad = currentHighlight();
    const viewModeOnLoad = csf._storedViewMode();
    let highlightPending = false;
    // The landing on a row the server rendered, until it has scrolled
    let landingTimer = null;
    if (highlightOnLoad !== null) {
        const onPage =
            document.getElementById(`music-${highlightOnLoad}`) ||
            document.getElementById(`music-${highlightOnLoad}-grid`);
        if (onPage) {
            landingTimer = setTimeout(() => {
                landingTimer = null;
                scrollToAlbumById(highlightOnLoad, viewModeOnLoad);
            }, 300);
        } else {
            highlightPending = true;
        }
    }
    /**
     * Land again on a highlighted album the engine has just rendered from
     * data of another version, which may have moved it: bring its row onto
     * the page, then, after a beat, scroll to it and flash it. The beat is
     * the one the landing waits on load: the page above the list is still
     * laying out, and a scroll at once fell short of the album. A reader who
     * scrolls, clicks or types during it keeps their place, with the album
     * flashed where it is.
     */
    const landOnHighlightAgain = () => {
        const position = csf.renderer.currentItems.findIndex(
            album => album.id === highlightOnLoad
        ) + 1;
        // Not in this result set at all: nothing to land on.
        if (position === 0) return;
        csf.jumpTo(position);
        let moved = false;
        const events = ['wheel', 'touchstart', 'keydown', 'pointerdown'];
        const move = () => { moved = true; };
        events.forEach(type => window.addEventListener(type, move, { capture: true, passive: true }));
        setTimeout(() => {
            events.forEach(type => window.removeEventListener(type, move, { capture: true }));
            scrollToAlbumById(highlightOnLoad, csf.viewMode, { scroll: !moved });
        }, 300);
    };

    csf.init().then(async ok => {
        if (!ok) {
            // HTMX keeps the page. A
            // failed request has nobody left to answer it, so the controls
            // go back to the list (mediaListControls.rollBackToTheList) -
            // unless a newer one is on its way, which answers for itself.
            // Finished ones can still be listed (see the takeover below)
            const inFlight = [...pending].some(([xhr, element]) =>
                element === form && xhr.readyState !== XMLHttpRequest.DONE
            );
            // Still tracked: a request that fails before Alpine starts the
            // controls is answered by them as they start, from csf.failedParams
            pending.clear();
            csf.failed = true;
            if (failedParams && !inFlight) {
                // The controls compare it with what the reader has done since
                window.dispatchEvent(new CustomEvent('client-engine-failed', {
                    detail: { parameters: failedParams },
                }));
            }
            return;
        }
        ready = true;
        csf.attach(form);

        // The server rendered its own Load More button, whose HTMX request
        // is suppressed from here on, so paging is driven by the engine
        // instead. Delegated, because every later page rewrites the button.
        document.addEventListener('click', event => {
            const button = event.target.closest('.load-more-button');
            if (!button) return;
            event.preventDefault();
            csf.loadMore();
        });
        // Load Previous is only ever drawn by the engine, after a jump.
        document.addEventListener('click', event => {
            if (!event.target.closest('.load-previous-button')) return;
            event.preventDefault();
            csf.loadPrevious();
        });

        // Only a change with a detail, which is commit()'s: every control
        // writes the form through it, a search included. A field's own
        // change carries none, and the search box's fires as it loses
        // focus - so answering it re-rendered during the mousedown of
        // whatever was clicked next, and the click landed on nothing. The controls also
        // mark a burst's trailing commit, which the user experiences as the
        // same change: one history entry, not two.
        form.addEventListener('change', event => {
            if (!event.detail) return;
            rerender({ replace: Boolean(event.detail.historyReplace) });
        });
        form.addEventListener('submit', event => {
            event.preventDefault();
            rerender();
        });

        // The list/grid toggle lives in the results header, outside this
        // form, and announces itself rather than reaching in here.
        window.addEventListener('media-view-mode', event => {
            csf.setViewMode(event.detail && event.detail.mode);
        });

        initAlbumJumpToRank(csf);

        // Back and Forward are the engine's from here, every entry htmx
        // pushed included: the page took popstate from htmx (music/home.html),
        // whose answer was to swap the whole body back in and leave all of
        // this wired to a form no longer on the page.
        window.addEventListener('popstate', () => {
            // The URL moved under us; re-read it into the form and re-render.
            // A landing page's bare path stands for its own filters
            const params = landingFilterParams(
                window.albumLandingPath, window.albumLandingSearch
            );
            [
                'q', 'start', 'end', 'artists', 'genres', 'listened', 'sort', 'dir'
            ].forEach(name => {
                const field = form.querySelector(`[name="${name}"]`);
                if (field) field.value = params.get(name) || '';
            });
            rerender({ push: false, highlightId: currentHighlight() });
        });

        // Nothing is re-rendered on load: the server already rendered the
        // form's filter state, and re-rendering would only make the page
        // flicker. The engine takes over from the next interaction - except
        // to answer what the load overtook, which would otherwise land on top
        // of the engine's renders or go unanswered, to render a form a
        // failed request left ahead of the list (formAhead, below), and to
        // page down to a highlighted album the server did not render.
        // Finished requests can still be listed: one whose element was
        // swapped out reports its end to that element alone, and one whose
        // swap threw never reports it. The second's button is still on the
        // page, so isConnected below would not drop it.
        const inFlight = [...pending].filter(
            ([xhr]) => xhr.readyState !== XMLHttpRequest.DONE
        );
        tracking(false);
        pending.clear();
        // On the xhr itself: htmx answers htmx:abort only from an element
        // still in the page. htmx reports these as errors in the console;
        // nothing has gone wrong
        inFlight.forEach(([xhr]) => xhr.abort());
        const filterRequest = inFlight.some(([, element]) => element === form);
        // A button that has left the page asked for a list that has gone too
        const pageRequest = inFlight.some(([, element]) =>
            element.isConnected && element.matches('.load-more-button')
        );
        // A filter request that failed before now (a 429, a 500, the
        // network) left the form on the filters it asked for, while the list
        // stayed on the ones it was rendered with, and Load More then
        // appended the form's rows to the server's. The sidebar says what
        // the reader last asked for, so that is what the engine renders.
        // Compared, not remembered: both states are on the page. Except a
        // search still being typed, which its own commit will answer -
        // unless the search's own request is the one that failed.
        const typing = document.activeElement &&
            // Either search box: the sidebar's and the mobile sheet's
            document.activeElement.matches('[data-filter-search]');
        // A search whose own request failed is not still being typed: the
        // box holds exactly the query that was sent, as htmx sent it. One
        // typed since, or an older failure of another filter, is. Untrimmed:
        // "pink " typed after a failed "pink" trims to it, and was rendered
        // and pushed mid-word
        const searchFailed = Boolean(failedParams) && typing &&
            htmxParameter(failedParams, 'q') === document.activeElement.value;
        const masked = typing && !searchFailed;
        const comparable = filters => JSON.stringify(
            masked ? Object.assign({}, filters, { q: '' }) : filters
        );
        const rendered = csf.renderedFilters();
        const formAhead = Boolean(rendered) &&
            comparable(csf.readFilters(form)) !== comparable(rendered);
        if (filterRequest || formAhead) {
            // Not pushed mid-search: the query is half typed, and its commit,
            // still to come, pushes the whole one. A failed search's commit
            // has been spent, so it is pushed here
            rerender({ push: !masked });
        } else if (!csf.followsPage()) {
            // The data is not the version the page was rendered from, so its
            // rows cannot continue the page's: the same positions are
            // rendered from it, a `?page=N` link's included, and then a page
            // the load overtook. The filters are the page's, so the URL stays
            const start = csf.pageStart;
            const shown = loadedAlbumCount();
            const page = start === 0 && shown <= csf.renderer.PAGE_SIZE;
            // The render replaces the highlighted row the link landed on,
            // and the new data may move the album. Read first: a reader
            // still at the landing - looking at the row, or on a page whose
            // landing has yet to scroll, which this one replaces - is taken
            // to the album, wherever it is now, and one who has moved on
            // keeps their place
            const landed = highlightOnLoad !== null && !highlightPending;
            const atLanding = landed &&
                (landingTimer !== null || albumInView(highlightOnLoad));
            clearTimeout(landingTimer);
            landingTimer = null;
            csf.applyFilters(csf.readFilters(form), {
                range: page ? null : [start, start + shown]
            });
            if (pageRequest) csf.loadMore();
            if (atLanding) {
                landOnHighlightAgain();
            } else if (landed) {
                scrollToAlbumById(highlightOnLoad, csf.viewMode, { scroll: false });
            }
        } else if (pageRequest) {
            csf.loadMore();
        } else if (csf.pageStart > 0) {
            // A `?page=N` link: the rows above it get their Load Previous,
            // and the count names the range
            csf._syncRendererWithPage();
            csf._updatePaging();
        }
        if (highlightPending) {
            csf._syncRendererWithPage();
            const position = csf.renderer.currentItems.findIndex(
                album => album.id === highlightOnLoad
            ) + 1;
            // Not in this result set at all: nothing to land on.
            if (position > 0) {
                csf.jumpTo(position);
                scrollToAlbumById(highlightOnLoad, csf.viewMode);
            }
        }
    });
}

if (typeof window !== 'undefined') {
    window.AlbumClientSideFiltering = AlbumClientSideFiltering;
    window.getAlbumClientSideFiltering = getAlbumClientSideFiltering;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAlbumFiltering);
    } else {
        initAlbumFiltering();
    }
}
