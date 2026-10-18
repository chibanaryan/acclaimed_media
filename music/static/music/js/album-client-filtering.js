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
    }

    /** The sessionStorage key, versioned so stale data is never read. */
    static storageKey(version) {
        return `albumData:${version}`;
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

        return {
            q: text('q'),
            start: number('start'),
            end: number('end'),
            artists: ids('artists'),
            genres: ids('genres'),
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
        return Boolean(
            filters.q ||
            filters.start !== undefined ||
            filters.end !== undefined ||
            filters.artists.length ||
            filters.genres.length
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
                '<div class="alert"><span class="mdi mdi-album"></span>' +
                '<span>Nothing here. Try widening the year range or ' +
                'clearing the search.</span></div>';
        } else {
            this.renderer.render(albums, container, {
                showRank,
                highlightId: options.highlightId || null
            });
        }

        this._updateCount(Math.min(total, this.renderer.PAGE_SIZE), total);
        this._updateLoadMore(total);
        return { total };
    }

    /** @private */
    _updateCount(loaded, total) {
        const count = document.querySelector('#album-results-container .result-count');
        if (count) {
            count.innerHTML = this.renderer.getResultSummaryHtml(loaded, total);
        }
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
        container.className = 'load-more-container flex justify-center mt-4';
        container.innerHTML = html;
        if (!existing) {
            document.getElementById('album-results-container').appendChild(container);
        }

        const button = container.querySelector('.load-more-button');
        if (button) {
            button.addEventListener('click', () => this.loadMore(), { once: true });
        }
    }

    /** Append the next page and refresh the count and button. */
    loadMore() {
        const container = document.getElementById('album-list-container');
        if (!container || !this.isInitialized) return;

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
            const button = wrapper.querySelector('.load-more-button');
            if (button) {
                button.addEventListener('click', () => this.loadMore(), { once: true });
            }
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
        if (filters.sort && filters.sort !== 'rank') params.set('sort', filters.sort);
        if (filters.dir && filters.dir !== 'asc') params.set('dir', filters.dir);

        const query = params.toString();
        window.history.pushState({}, '', query ? `?${query}` : window.location.pathname);
    }
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

    const suppressHtmx = event => {
        if (ready) event.preventDefault();
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

    csf.init().then(ok => {
        if (!ok) return;
        ready = true;

        // The decade chips are their own hx-gets; they set the year inputs
        // and re-run instead.
        form.querySelectorAll('button[name="decade"]').forEach(chip => {
            chip.addEventListener('click', () => {
                const url = new URL(chip.getAttribute('hx-get'), window.location.origin);
                const start = url.searchParams.get('start') || '';
                const end = url.searchParams.get('end') || '';
                const startInput = form.querySelector('input[name="start"]');
                const endInput = form.querySelector('input[name="end"]');
                const selected = chip.classList.contains('mobile-filter-chip-selected');
                if (startInput) startInput.value = selected ? '' : start;
                if (endInput) endInput.value = selected ? '' : end;
                form.querySelectorAll('button[name="decade"]').forEach(other => {
                    other.classList.toggle(
                        'mobile-filter-chip-selected',
                        other === chip && !selected
                    );
                });
                rerender();
            });
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

        window.addEventListener('popstate', () => {
            // The URL moved under us; re-read it into the form and re-render.
            const params = new URLSearchParams(window.location.search);
            ['q', 'start', 'end', 'artists', 'genres', 'sort', 'dir'].forEach(name => {
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
