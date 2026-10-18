/**
 * Acclaimed Albums - Client-Side Filtering Integration
 *
 * Takes over the album rankings page's filter form once the whole corpus is
 * in the browser: ~500 albums, about 38 KB gzipped, so filtering a 100-row
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
        this.renderer.currentItems = albums;
        this.renderer._currentViewMode = this.viewMode;
        this.renderer._currentShowRank = this._isFiltered(filters)
            ? 'filtered'
            : 'alltime';
        const loaded = loadedAlbumCount();
        this.renderer.currentPage = Math.max(
            1,
            Math.ceil(loaded / this.renderer.PAGE_SIZE)
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
     * sessionStorage rather than IndexedDB or localStorage: the rankings are
     * staff-only, unreleased editorial data, and a tab-scoped copy is the
     * shortest lifetime that still avoids refetching on every navigation.
     * @private
     */
    async _loadData() {
        const version = window.albumDataVersion || '';
        const key = AlbumClientSideFiltering.storageKey(version);

        if (version) {
            try {
                const stored = sessionStorage.getItem(key);
                if (stored) return JSON.parse(stored);
            } catch (e) {
                // Private mode, blocked storage, or a truncated entry.
            }
        }

        const response = await fetch(window.albumDataUrl || '/api/music/all/', {
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
        return data;
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
        const text = name => (data.get(name) || '').toString().trim();
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
            artists: ids('artists'),
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
     */
    applyFilters(filters, options = {}) {
        if (!this.isInitialized) return null;

        this.currentFilters = filters;
        const { albums, total } = this.engine.apply(filters);
        const showRank = this._isFiltered(filters) ? 'filtered' : 'alltime';

        const container = document.getElementById('album-list-container');
        if (!container) return null;

        this.renderer.reset();
        if (total === 0) {
            container.innerHTML =
                '<div class="text-base-content/85 py-8 text-center">' +
                'No albums match your filters.</div>';
        } else {
            this.renderer.render(albums, container, {
                showRank,
                highlightId: options.highlightId || null,
                viewMode: this.viewMode
            });
        }

        this._updateCount(Math.min(total, this.renderer.PAGE_SIZE), total);
        this._updateLoadMore(total);
        this._publishFacets(filters, albums);
        return { total };
    }

    /**
     * Refresh both result-count lines - the controls partial renders one for
     * desktop and a compact one for mobile.
     * @private
     */
    _updateCount(loaded, total) {
        const lines = document.querySelectorAll(
            '#album-results-container [data-result-count]'
        );
        lines.forEach(line => {
            line.innerHTML = this.renderer.getResultSummaryHtml(loaded, total, {
                compact: line.dataset.resultCount === 'mobile'
            });
        });
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
        const facets = this.engine.facets(filters);
        window.dispatchEvent(
            new CustomEvent('year-counts-update', { detail: facets.years })
        );
        window.dispatchEvent(
            new CustomEvent('genre-counts-update', { detail: facets.genres })
        );
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
    _updateLoadMore(total) {
        const existing = document.querySelector(
            '#album-results-container .load-more-container'
        );
        const remaining = Math.max(total - this.renderer.PAGE_SIZE, 0);

        if (!remaining) {
            if (existing) existing.remove();
            return;
        }

        const html = this.renderer.getLoadMoreHtml({ hasMore: true, remaining });
        const container = existing || document.createElement('div');
        container.id = 'load-more-container';
        container.className = 'load-more-container text-center my-6';
        container.innerHTML = html;
        if (!existing) {
            document.getElementById('album-results-container').appendChild(container);
        }

    }

    /** Append the next page and refresh the count and button. */
    loadMore() {
        const container = document.getElementById('album-list-container');
        if (!container || !this.isInitialized) return;

        this._syncRendererWithPage();

        const showRank = this._isFiltered(this.currentFilters)
            ? 'filtered'
            : 'alltime';
        const state = this.renderer.loadMore(container, { showRank });

        this._updateCount(state.loaded, state.total);

        const wrapper = document.querySelector(
            '#album-results-container .load-more-container'
        );
        if (!state.hasMore) {
            if (wrapper) wrapper.remove();
            return;
        }
        if (wrapper) {
            wrapper.innerHTML = this.renderer.getLoadMoreHtml(state);
        }
    }

    /**
     * Mirror the filter state into the URL, as `hx-push-url` did.
     * @private
     */
    pushUrl(filters) {
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

        const query = params.toString();
        window.history.pushState({}, '', query ? `?${query}` : window.location.pathname);
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
    const index = position - 1;

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

    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    highlight.forEach(el => el.classList.add('is-highlighted'));
    setTimeout(() => {
        highlight.forEach(el => el.classList.remove('is-highlighted'));
    }, 3000);
}

/** How many rows are on the page now, in whichever view is showing. */
function loadedAlbumCount() {
    const container = document.getElementById('album-list-container');
    if (!container) return 0;
    const selector = container.classList.contains('view-grid')
        ? '.media-card-grid'
        : '.media-row.desktop';
    return container.querySelectorAll(selector).length;
}

/**
 * Wire the jump-to-rank boxes in the results header.
 *
 * The controls partial renders a pair of them, one for each breakpoint, so
 * the handlers are delegated from the document rather than bound per input.
 * With the engine ready this pages through the data in memory; without it the
 * page's own HTMX load-more is clicked instead, which is slower but keeps the
 * box working if the bundle never arrives.
 */
function initAlbumJumpToRank(csf) {
    const jump = async input => {
        const target = parseInt(input.value, 10);
        // The renderer holds the current result set once it has rendered
        // one; before that the server's own count is on the input.
        const rendered = csf.isReady() ? csf.renderer.currentItems.length : 0;
        const total = rendered || parseInt(input.dataset.total, 10) || 0;

        if (!Number.isFinite(target) || target < 1 || (total && target > total)) {
            input.classList.add('input-error');
            setTimeout(() => input.classList.remove('input-error'), 1000);
            return;
        }

        while (loadedAlbumCount() < target) {
            const before = loadedAlbumCount();
            if (csf.isReady()) {
                csf.loadMore();
            } else {
                const button = document.querySelector(
                    '#load-more-container .load-more-button'
                );
                if (!button) break;
                button.click();
                // Give HTMX a moment to swap the next page in.
                await new Promise(resolve => setTimeout(resolve, 400));
            }
            if (loadedAlbumCount() === before) break;
        }

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

    const currentHighlight = () => {
        const highlight = new URLSearchParams(window.location.search).get('highlight');
        const parsed = parseInt(highlight, 10);
        return Number.isFinite(parsed) ? parsed : null;
    };

    const rerender = ({ push = true, highlightId = null } = {}) => {
        const filters = csf.readFilters(form);
        csf.applyFilters(filters, { highlightId });
        if (push) csf.pushUrl(filters);
    };

    // A genre clicked in a row filters by it, as it does on the games
    // rankings page. Bound before init resolves so the click works either
    // way: the select is the filter's single source of truth, and a plain
    // change event is what both HTMX and the engine below listen for.
    document.addEventListener('add-genre', event => {
        const select = form.querySelector('[name="genres"]');
        const genreId = event.detail && event.detail.genreId;
        if (!select || !genreId) return;
        select.value = String(genreId);

        if (!ready) {
            select.dispatchEvent(new Event('change', { bubbles: true }));
            return;
        }
        const highlight = parseInt(event.detail.itemId, 10);
        rerender({ highlightId: Number.isFinite(highlight) ? highlight : null });
    });

    // A toggle can change whether a row still belongs in the results.
    // media-tracking.js has already updated the Sets the engine reads by the
    // time this fires, so re-filtering is all that is needed.
    window.addEventListener('album-status-changed', () => {
        if (!ready) return;
        const filters = csf.readFilters(form);
        if (!filters.listened.length) return;
        rerender({ push: false, highlightId: currentHighlight() });
    });

    csf.init().then(ok => {
        if (!ok) return;
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

        form.addEventListener('change', () => rerender());
        form.addEventListener('submit', event => {
            event.preventDefault();
            rerender();
        });

        let typingTimer = null;
        const search = form.querySelector('input[name="q"]');
        if (search) {
            search.addEventListener('input', () => {
                clearTimeout(typingTimer);
                typingTimer = setTimeout(() => rerender(), 350);
            });
        }

        // The list/grid toggle lives in the results header, outside this
        // form, and announces itself rather than reaching in here.
        window.addEventListener('media-view-mode', event => {
            csf.setViewMode(event.detail && event.detail.mode);
        });

        initAlbumJumpToRank(csf);

        window.addEventListener('popstate', () => {
            // The URL moved under us; re-read it into the form and re-render.
            const params = new URLSearchParams(window.location.search);
            [
                'q', 'start', 'end', 'artists', 'genres', 'listened', 'sort', 'dir'
            ].forEach(name => {
                const field = form.querySelector(`[name="${name}"]`);
                if (field) field.value = params.get(name) || '';
            });
            rerender({ push: false, highlightId: currentHighlight() });
        });

        // Nothing is re-rendered on load: the server already rendered this
        // exact filter state, and re-rendering would only make the page
        // flicker. The engine takes over from the next interaction.
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
