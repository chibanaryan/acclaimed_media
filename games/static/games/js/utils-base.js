/**
 * Acclaimed Games - Base Utilities
 *
 * Essential utilities that must be available before Alpine.js initializes.
 * Includes core functions and filter/search utilities.
 */

// ============================================================
// FETCH UTILITIES
// ============================================================

/**
 * Creates HTMX-compatible fetch headers
 * @param {string} targetId - The HTMX target element ID
 * @returns {Object} Headers object for fetch
 */
function createHtmxHeaders(targetId = 'content') {
    return {
        'X-Requested-With': 'XMLHttpRequest',
        'HX-Request': 'true',
        'HX-Target': targetId
    };
}

/**
 * Fetches HTML content with HTMX headers and AbortController support
 * @param {string} url - URL to fetch
 * @param {AbortSignal} signal - AbortController signal
 * @param {string} targetId - HTMX target ID
 * @returns {Promise<string>} HTML response text
 */
async function fetchHtml(url, signal, targetId = 'content') {
    const response = await fetch(url, {
        headers: createHtmxHeaders(targetId),
        signal: signal
    });
    return response.text();
}

/**
 * Parses HTML string and extracts elements by selector
 * @param {string} html - HTML string to parse
 * @param {Array<{selector: string, targetId: string}>} updates - Elements to extract
 * @returns {Object} Map of targetId to innerHTML
 */
function parseAndExtract(html, updates) {
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, 'text/html');
    const result = {};

    updates.forEach(({ selector, targetId }) => {
        const element = doc.querySelector(selector);
        if (element) {
            result[targetId] = element.innerHTML;
        }
    });

    return result;
}

/**
 * Updates multiple DOM elements from parsed content
 * @param {Object} contentMap - Map of elementId to innerHTML
 */
function updateDomElements(contentMap) {
    Object.entries(contentMap).forEach(([elementId, innerHTML]) => {
        const element = document.getElementById(elementId);
        if (element) {
            element.innerHTML = innerHTML;
        }
    });
}

// ============================================================
// TIMING UTILITIES
// ============================================================

/**
 * Creates a debounced function
 * @param {Function} fn - Function to debounce
 * @param {number} delay - Delay in milliseconds
 * @returns {Function} Debounced function with cancel method
 */
function debounce(fn, delay) {
    let timeoutId = null;

    const debounced = function(...args) {
        if (timeoutId) {
            clearTimeout(timeoutId);
        }
        timeoutId = setTimeout(() => {
            fn.apply(this, args);
            timeoutId = null;
        }, delay);
    };

    debounced.cancel = function() {
        if (timeoutId) {
            clearTimeout(timeoutId);
            timeoutId = null;
        }
    };

    return debounced;
}

/**
 * Creates a debounced function that also fires on the leading edge.
 *
 * The first call after a quiet spell runs at once; calls arriving within
 * `delay` of the last one are coalesced into a single trailing run. A plain
 * trailing debounce made every single click on a year, decade, genre or
 * platform wait out the full delay before anything changed - most of the
 * ~200 ms between a click and the filtered list - while bursts (quick
 * successive clicks, the end of a drag) still need collapsing.
 *
 * `fn` receives `{ followsLeading }`: true for a trailing run in a burst
 * that already ran on its leading edge, so the caller can replace rather
 * than add a history entry for what the user experiences as one change.
 *
 * Options:
 * - `canLead()`: asked at the start of each burst; while it answers false
 *   the burst behaves as a plain trailing debounce.
 * - `keyOf()`: the state a run would apply, read when the run executes
 *   (after `schedule`), not when it was queued. A trailing run whose key
 *   equals the leading run's is skipped as a repeat of it. Reading it late
 *   matters: a year click's mouseup and click both request an update, and
 *   by the time the scheduled leading run executes it sees the click's
 *   final state, so the trailing run is a repeat rather than a second render.
 * - `schedule(run)`: how a run is queued, e.g. `afterNextPaint`.
 *
 * `cancel()` drops the pending trailing run and any run already queued by
 * `schedule`, so nothing stale applies after a Back or a teardown.
 *
 * @param {Function} fn - Function to debounce
 * @param {number} delay - Quiet period in milliseconds
 * @param {Object} [options] - `canLead`, `keyOf`, `schedule`
 * @returns {Function} Debounced function with cancel method
 */
function debounceLeading(fn, delay, options) {
    const opts = options || {};
    const schedule = opts.schedule || (run => run());
    let timeoutId = null;
    let pending = false;
    let pendingThis = null;
    let ledThisBurst = false;
    let leadingKey;
    let generation = 0;

    const run = (self, followsLeading) => {
        const token = generation;
        schedule(() => {
            if (token !== generation) return;
            const key = opts.keyOf ? opts.keyOf.call(self) : undefined;
            if (followsLeading && opts.keyOf && key === leadingKey) return;
            leadingKey = followsLeading ? undefined : key;
            fn.call(self, { followsLeading });
        });
    };

    const debounced = function() {
        if (timeoutId === null && (!opts.canLead || opts.canLead())) {
            ledThisBurst = true;
            run(this, false);
        } else {
            if (timeoutId !== null) {
                clearTimeout(timeoutId);
            }
            pending = true;
            pendingThis = this;
        }
        timeoutId = setTimeout(() => {
            timeoutId = null;
            const followsLeading = ledThisBurst;
            ledThisBurst = false;
            if (pending) {
                const self = pendingThis;
                pending = false;
                pendingThis = null;
                run(self, followsLeading);
            }
        }, delay);
    };

    debounced.cancel = function() {
        if (timeoutId) {
            clearTimeout(timeoutId);
            timeoutId = null;
        }
        pending = false;
        pendingThis = null;
        ledThisBurst = false;
        leadingKey = undefined;
        generation += 1;
    };

    return debounced;
}

/**
 * Map each item's key to its position in `list`, first match winning as
 * find() would.
 *
 * The filter sidebars receive the page's reactive arrays: reading `list[i]`
 * through such an index tracks that one item, where `list.find()` read -
 * and so subscribed to - every item, on every re-evaluation.
 *
 * @param {Array} list - Items to index
 * @param {Function} keyOf - The key for an item
 * @returns {Object} key -> position
 */
function indexBy(list, keyOf) {
    const index = {};
    (list || []).forEach((item, i) => {
        const key = keyOf(item);
        if (!Object.prototype.hasOwnProperty.call(index, key)) {
            index[key] = i;
        }
    });
    return index;
}

/**
 * Runs `fn` once the browser has painted the current frame.
 *
 * A click handler that does a filter update's work synchronously holds back
 * the paint that shows the click registered, which is what INP measures: at
 * a 4x CPU slowdown that was ~300-400 ms. Waiting for the next animation
 * frame and then one more task lets that paint land first, for about one
 * frame of extra delay before the update itself.
 *
 * @param {Function} fn - Work to run after the next paint
 */
function afterNextPaint(fn) {
    if (typeof requestAnimationFrame !== 'function') {
        setTimeout(fn, 0);
        return;
    }
    requestAnimationFrame(() => setTimeout(fn, 0));
}

/**
 * Creates a throttled function
 * @param {Function} fn - Function to throttle
 * @param {number} limit - Minimum time between calls in milliseconds
 * @returns {Function} Throttled function
 */
function throttle(fn, limit) {
    let lastCall = 0;

    return function(...args) {
        const now = Date.now();
        if (now - lastCall >= limit) {
            lastCall = now;
            return fn.apply(this, args);
        }
    };
}

/**
 * Creates a throttled function that can be force-called
 * @param {Function} fn - Function to throttle
 * @param {number} limit - Minimum time between calls
 * @returns {Object} Object with call() and force() methods
 */
function throttleWithForce(fn, limit) {
    let lastCall = 0;

    return {
        call(...args) {
            const now = Date.now();
            if (now - lastCall >= limit) {
                lastCall = now;
                return fn.apply(this, args);
            }
        },
        force(...args) {
            lastCall = 0;
            return fn.apply(this, args);
        }
    };
}

// ============================================================
// ABORT CONTROLLER MANAGER
// ============================================================

/**
 * Manages AbortController lifecycle for fetch requests
 * Ensures only one request is active at a time
 */
class FetchManager {
    constructor() {
        this.controller = null;
    }

    /**
     * Aborts any pending request and creates new controller
     * @returns {AbortSignal} Signal for the new request
     */
    newRequest() {
        if (this.controller) {
            this.controller.abort();
        }
        this.controller = new AbortController();
        return this.controller.signal;
    }

    /**
     * Aborts current request if any
     */
    abort() {
        if (this.controller) {
            this.controller.abort();
            this.controller = null;
        }
    }
}

// ============================================================
// URL UTILITIES
// ============================================================

/**
 * Builds URL parameters from filter object
 * @param {Object} filters - Filter values
 * @param {Object} options - Options for building params
 * @param {boolean} options.preservePage - Keep current page parameter
 * @returns {URLSearchParams} Built parameters
 */
function buildFilterParams(filters, options = {}) {
    const params = new URLSearchParams();

    if (options.preservePage) {
        const currentPage = new URLSearchParams(window.location.search).get('page');
        if (currentPage) {
            params.set('page', currentPage);
        }
    }

    if (filters.q) params.set('q', filters.q);
    if (filters.start) params.set('start', filters.start);
    if (filters.end) params.set('end', filters.end);
    if (filters.genres && filters.genres.length) {
        const genreIds = filters.genres.map(g =>
            (typeof g === 'object' && g !== null && g.id !== undefined) ? g.id : g
        ).filter(id => id !== null && id !== undefined);
        if (genreIds.length > 0) params.set('genres', genreIds.join(','));
    }
    if (filters.platforms && filters.platforms.length) {
        const platformIds = filters.platforms.map(p =>
            (typeof p === 'object' && p !== null && p.id !== undefined) ? p.id : p
        ).filter(id => id !== null && id !== undefined);
        if (platformIds.length > 0) params.set('platforms', platformIds.join(','));
    }
    if (filters.series && filters.series.length) {
        const seriesIds = filters.series.map(s =>
            (typeof s === 'object' && s !== null && s.id !== undefined) ? s.id : s
        ).filter(id => id !== null && id !== undefined);
        if (seriesIds.length > 0) params.set('series', seriesIds.join(','));
    }
    if (filters.sort && filters.sort !== 'rank') params.set('sort', filters.sort);
    if (filters.sortDirection && filters.sortDirection !== 'asc') params.set('dir', filters.sortDirection);
    // Handle played as array (multi-select) or string (backwards compatibility)
    if (filters.played) {
        if (Array.isArray(filters.played) && filters.played.length > 0) {
            params.set('played', filters.played.join(','));
        } else if (typeof filters.played === 'string' && filters.played) {
            params.set('played', filters.played);
        }
    }
    if (filters.highlight) params.set('highlight', filters.highlight);

    // HLTB filter parameters
    if (filters.hltb_mode && filters.hltb_mode !== 'main') {
        params.set('hltb_mode', filters.hltb_mode);
    }
    if (filters.hltb_min !== null && filters.hltb_min !== undefined) {
        params.set('hltb_min', filters.hltb_min);
        // If min is set but max is null, use "unlimited" for no upper limit
        const maxValue = (filters.hltb_max !== null && filters.hltb_max !== undefined)
            ? filters.hltb_max
            : 'unlimited';
        params.set('hltb_max', maxValue);
    } else if (filters.hltb_max !== null && filters.hltb_max !== undefined) {
        // If only max is set (no min), still include it
        params.set('hltb_max', filters.hltb_max);
    }

    return params;
}

/**
 * Normalizes URL string by decoding common URL-encoded characters
 * @param {string} url - URL string to normalize
 * @returns {string} Normalized URL
 */
function normalizeUrl(url) {
    return url.replace(/%2C/g, ',');
}

/**
 * Reads the SEO clean-URL map embedded by the home page template
 * (#seo-urls-data json_script). Cached after first parse.
 * @returns {Object|null} {genres: {id: slug}, platforms: {id: slug},
 *                         years: [int], decades: [int]} or null
 */
function getSeoUrlData() {
    if (window._seoUrlData !== undefined) return window._seoUrlData;
    const el = document.getElementById('seo-urls-data');
    window._seoUrlData = el ? JSON.parse(el.textContent) : null;
    return window._seoUrlData;
}

/**
 * Returns the clean SEO page URL (/games/<slug>/, /games/<year>/,
 * /games/<decade>s/) when the built filter params match exactly one SEO
 * ranking page, otherwise null. Used so pushed history URLs are the
 * canonical, indexable pages whenever possible (shared links then point
 * at them instead of query-param URLs that canonicalize to /).
 * @param {URLSearchParams} params - Params from buildFilterParams
 * @param {number} minYear - Global minimum release year
 * @param {number} maxYear - Global maximum release year
 * @returns {string|null} Clean URL path or null
 */
function seoCleanUrl(params, minYear, maxYear) {
    const data = getSeoUrlData();
    if (!data) return null;

    // Work on a copy; a full year range means "no year filter"
    const p = new URLSearchParams(params.toString());
    const start = parseInt(p.get('start'));
    const end = parseInt(p.get('end'));
    if (start === minYear && end === maxYear) {
        p.delete('start');
        p.delete('end');
    }

    const keys = Array.from(p.keys()).sort().join(',');
    if (keys === 'genres') {
        const slug = data.genres[p.get('genres')];
        if (slug) return '/games/' + slug + '/';
    } else if (keys === 'platforms') {
        const slug = data.platforms[p.get('platforms')];
        if (slug) return '/games/' + slug + '/';
    } else if (keys === 'end,start') {
        if (start === end && data.years.indexOf(start) !== -1) {
            return '/games/' + start + '/';
        }
        if (start % 10 === 0 && end === start + 9 && data.decades.indexOf(start) !== -1) {
            return '/games/' + start + 's/';
        }
    }
    return null;
}

/**
 * Maps a clean SEO page path back to its equivalent query string so
 * history navigation (popstate/bfcache) can restore filter state from
 * URLs that carry no search params.
 * @param {string} pathname - window.location.pathname
 * @returns {string} Query string like 'genres=201' or '' if not an SEO path
 */
function seoPathSearch(pathname) {
    const data = getSeoUrlData();
    if (!data) return '';

    const decadeMatch = pathname.match(/^\/games\/(\d{3}0)s\/$/);
    if (decadeMatch) {
        const decade = parseInt(decadeMatch[1]);
        if (data.decades.indexOf(decade) !== -1) {
            return 'start=' + decade + '&end=' + (decade + 9);
        }
        return '';
    }
    const yearMatch = pathname.match(/^\/games\/(\d{4})\/$/);
    if (yearMatch) {
        const year = parseInt(yearMatch[1]);
        if (data.years.indexOf(year) !== -1) {
            return 'start=' + year + '&end=' + year;
        }
        return '';
    }
    const slugMatch = pathname.match(/^\/games\/([a-z0-9-]+)\/$/);
    if (slugMatch) {
        for (const id in data.genres) {
            if (data.genres[id] === slugMatch[1]) return 'genres=' + id;
        }
        for (const id in data.platforms) {
            if (data.platforms[id] === slugMatch[1]) return 'platforms=' + id;
        }
    }
    return '';
}

/**
 * Keep Tab inside a modal panel: from its last focusable element Tab wraps
 * to the first, and Shift+Tab from the first (or the panel itself) to the
 * last. For the mobile filter sheets, which are full-screen dialogs that
 * Tab used to walk straight out of into the page underneath.
 * @param {KeyboardEvent} event - The Tab keydown
 * @param {HTMLElement} container - The dialog
 */
function trapTabFocus(event, container) {
    const focusable = Array.from(container.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
        'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )).filter(el => el.offsetParent !== null);
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && (document.activeElement === first || document.activeElement === container)) {
        event.preventDefault();
        last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
    }
}

/**
 * The page's filter params: the query string, plus whatever filter a clean
 * SEO path implies. A filter state with its own landing page is pushed as
 * that path (/games/2010s/), with no query string, so anything reading the
 * filters from location.search alone saw none there: jump to rank checked
 * against the whole ranking, and client-rendered rows showed all-time
 * ranks. Merged rather than used only as a fallback, because a landing URL
 * can still carry ?utm_source= or ?highlight=.
 * @returns {URLSearchParams}
 */
function currentFilterParams() {
    const params = new URLSearchParams(window.location.search);
    new URLSearchParams(seoPathSearch(window.location.pathname)).forEach((value, key) => {
        if (!params.has(key)) params.set(key, value);
    });
    return params;
}

/**
 * Updates URL with filter parameter and navigates
 * @param {string} paramName - Parameter name
 * @param {string} value - Parameter value
 * @param {string} baseUrl - Base URL to navigate to
 */
function updateFilterAndNavigate(paramName, value, baseUrl) {
    const params = new URLSearchParams(window.location.search);
    params.delete('page');
    if (value) {
        params.set(paramName, value);
    } else {
        params.delete(paramName);
    }
    window.location.href = baseUrl + '?' + params.toString();
}

// ============================================================
// LOADING STATE UTILITIES
// ============================================================

/**
 * Adds loading class to element
 * @param {string} elementId - Element ID
 */
function setLoading(elementId) {
    const element = document.getElementById(elementId);
    if (element) {
        element.classList.add('is-loading');
    }
}

/**
 * Removes loading class from element
 * @param {string} elementId - Element ID
 */
function clearLoading(elementId) {
    const element = document.getElementById(elementId);
    if (element) {
        element.classList.remove('is-loading');
    }
}

// ============================================================
// SEARCH UTILITIES
// ============================================================

/**
 * Performs game search API call
 * @param {string} query - Search query
 * @param {number} limit - Max results
 * @param {string} apiUrl - API endpoint URL
 * @returns {Promise<Array>} Search results
 */
async function searchGames(query, limit, apiUrl) {
    const trimmedQuery = query.trim();
    if (trimmedQuery.length < 2) {
        return [];
    }

    const response = await fetch(
        `${apiUrl}?q=${encodeURIComponent(trimmedQuery)}&limit=${limit}`
    );

    if (!response.ok) {
        throw new Error('API request failed');
    }

    const data = await response.json();
    return data.results || [];
}

/**
 * Removes a filter item and updates the page via fetch
 * @param {Object} filters - Current filter state
 * @param {string} filterType - Type of filter ('genres' or 'platforms')
 * @param {number} index - Index of item to remove
 * @param {string} searchUrl - Base search URL
 * @param {Function} onUpdate - Callback after update (optional)
 */
async function removeFilterItem(filters, filterType, index, searchUrl, onUpdate) {
    filters[filterType] = filters[filterType].filter((_, i) => i !== index);

    const params = buildFilterParams(filters);
    const url = searchUrl + '?' + normalizeUrl(params.toString());

    try {
        const html = await fetchHtml(url, new AbortController().signal);
        const contentEl = document.getElementById('content');
        if (contentEl) {
            contentEl.innerHTML = html;
            window.history.pushState({}, '', url);
            if (typeof Alpine !== 'undefined') {
                Alpine.initTree(contentEl);
            }
        }
        if (onUpdate) onUpdate();
    } catch (err) {
        console.error('Error removing filter:', err);
    }
}

/**
 * Creates Alpine.js search component data
 * @param {string} apiUrl - API endpoint for search
 * @param {number} limit - Max results to return
 * @returns {Object} Alpine component data
 */
function createSearchData(apiUrl, limit = 5) {
    return {
        showMenu: false,
        q: '',
        results: [],
        loading: false,

        async loadResults() {
            const trimmedQ = this.q.trim();
            if (trimmedQ.length < 2) {
                this.results = [];
                this.loading = false;
                return;
            }
            this.loading = true;
            this.results = [];
            try {
                this.results = await searchGames(trimmedQ, limit, apiUrl);
            } catch (e) {
                console.error('Search error:', e);
                this.results = [];
            } finally {
                this.loading = false;
            }
        },

        reset() {
            this.showMenu = false;
            this.q = '';
            this.results = [];
            this.loading = false;
        }
    };
}

/**
 * Performs unified search API call for developers, games, and series
 * @param {string} query - Search query
 * @param {number} developerLimit - Max developer results
 * @param {number} gameLimit - Max game results
 * @param {number} seriesLimit - Max series results
 * @param {string} apiUrl - API endpoint URL
 * @returns {Promise<Object>} Search results with developers, games, and series arrays
 */
async function searchUnified(query, developerLimit, gameLimit, seriesLimit, apiUrl) {
    const trimmedQuery = query.trim();
    if (trimmedQuery.length < 2) {
        return { developers: [], games: [], series: [] };
    }

    const response = await fetch(
        `${apiUrl}?q=${encodeURIComponent(trimmedQuery)}&developer_limit=${developerLimit}&game_limit=${gameLimit}&series_limit=${seriesLimit}`
    );

    if (!response.ok) {
        throw new Error('API request failed');
    }

    const data = await response.json();
    return {
        developers: data.developers || [],
        games: data.games || [],
        series: data.series || []
    };
}

/**
 * Creates Alpine.js unified search component data (developers, games, and series)
 * @param {string} apiUrl - API endpoint for unified search
 * @param {number} developerLimit - Max developer results (default 3)
 * @param {number} gameLimit - Max game results (default 5)
 * @param {number} seriesLimit - Max series results (default 3)
 * @returns {Object} Alpine component data
 */
function createUnifiedSearchData(apiUrl, developerLimit = 3, gameLimit = 5, seriesLimit = 3) {
    return {
        showMenu: false,
        q: '',
        developers: [],
        games: [],
        series: [],
        loading: false,

        hasResults() {
            return this.developers.length > 0 || this.games.length > 0 || this.series.length > 0;
        },

        hasDeveloperResults() {
            return this.developers.length > 0;
        },

        hasGameResults() {
            return this.games.length > 0;
        },

        hasSeriesResults() {
            return this.series.length > 0;
        },

        async loadResults() {
            const trimmedQ = this.q.trim();
            if (trimmedQ.length < 2) {
                this.developers = [];
                this.games = [];
                this.series = [];
                this.loading = false;
                return;
            }
            this.loading = true;
            this.developers = [];
            this.games = [];
            this.series = [];
            try {
                const results = await searchUnified(trimmedQ, developerLimit, gameLimit, seriesLimit, apiUrl);
                this.developers = results.developers;
                this.games = results.games;
                this.series = results.series;
            } catch (e) {
                console.error('Search error:', e);
                this.developers = [];
                this.games = [];
                this.series = [];
            } finally {
                this.loading = false;
            }
        },

        reset() {
            this.showMenu = false;
            this.q = '';
            this.developers = [];
            this.games = [];
            this.series = [];
            this.loading = false;
        }
    };
}

// ============================================================
// YEAR PREVIEW UTILITIES
// ============================================================

// Guard to prevent duplicate listener registration (memory leak fix)
var _yearPreviewInitialized = false;

/**
 * Initializes year preview highlighting during year grid drag selection
 */
function initYearPreview() {
    if (_yearPreviewInitialized) return;
    _yearPreviewInitialized = true;
    window.addEventListener('year-preview', handleYearPreview);
}

/**
 * Handles year preview event from year grid drag selection
 * @param {CustomEvent} event - Event with detail: { active, start, end }
 */
function handleYearPreview(event) {
    const { active, start, end } = event.detail;
    const gameYears = document.querySelectorAll('.game-year[data-year]');

    if (!active) {
        gameYears.forEach(el => el.classList.remove('year-preview'));
        return;
    }

    gameYears.forEach(el => {
        const year = parseInt(el.dataset.year, 10);
        if (year >= start && year <= end) {
            el.classList.add('year-preview');
        } else {
            el.classList.remove('year-preview');
        }
    });
}

// ============================================================
// PLATFORM SEGMENT UTILITIES
// ============================================================

/**
 * Platform groups for title generation
 * Groups are checked in order - broader manufacturer groups first, then form factors
 * This ensures "Nintendo" is used when all Nintendo platforms are selected,
 * but "Nintendo Handheld" when only handhelds are selected
 */
var PLATFORM_GROUPS = [
    // Big manufacturer groups (checked first to collapse when all are selected)
    ['Nintendo', ['NES', 'SNES', 'N64', 'GC', 'Wii', 'WiiU', 'DS', '3DS', 'SW', 'SW2', 'GB', 'GBA', 'GBC', 'FDS']],
    ['PlayStation', ['PS', 'PS2', 'PS3', 'PS4', 'PS5', 'PSP', 'PSV', 'PSVR']],
    ['Sega', ['GEN', 'SMS', 'DC', 'SAT', 'GG', 'SCD']],
    // Other manufacturer groups
    ['Xbox', ['Xbox', 'X360', 'XB1', 'XBXS']],
    ['PC', ['WIN', 'DOS', 'LIN', 'MAC']],
    ['Arcade, Mobile & VR', ['ARC', 'AND', 'iOS', 'LMD', 'VR', 'BR']],
    ['Retro Consoles', ['A26', 'A52', 'A78', 'INTV', 'CV', 'TG16', '3DO', 'NG', 'JAG', 'LYNX', 'NGP', 'WS']],
    ['Microcomputer', ['VC20', 'C64', 'AMI', 'CD32', 'ZXS', 'CPC', 'BBCM', 'ARCH', 'PC88', 'PC98', 'FM7', 'FMT', 'SX1', 'MSX', 'A8', 'AST', 'A2', 'T80', 'TCC', 'PDP', 'HP21', 'E60']],
    // Form factor groups (checked after manufacturer groups)
    ['Nintendo Handheld', ['GB', 'GBC', 'GBA', 'DS', '3DS']],
    ['Nintendo Home Console', ['NES', 'FDS', 'SNES', 'N64', 'GC', 'Wii', 'WiiU', 'SW', 'SW2']],
    ['PlayStation Handheld', ['PSP', 'PSV']],
    ['PlayStation Home Console', ['PS', 'PS2', 'PS3', 'PS4', 'PS5', 'PSVR']],
    ['Sega Handheld', ['GG']],
    ['Sega Home Console', ['SMS', 'GEN', 'SCD', 'SAT', 'DC']],
    // Microcomputer form factor groups
    ['Commodore', ['VC20', 'C64', 'AMI', 'CD32']],
    ['UK Microcomputer', ['ZXS', 'CPC', 'BBCM', 'ARCH']],
    ['Japanese Microcomputer', ['PC88', 'PC98', 'FM7', 'FMT', 'SX1', 'MSX']],
    ['Atari Microcomputer', ['A8', 'AST']]
];

/**
 * Builds platform segment for dynamic title generation
 * Uses ES5 syntax to avoid HTML parsing issues with arrow functions
 * @param {Array} platforms - Array of platform objects with id, code, and name
 * @param {Array} selectedPlatformIds - Array of selected platform IDs (strings)
 * @returns {string} Platform segment for title (e.g., "Nintendo", "PC", "Video")
 */
function buildPlatformSegment(platforms, selectedPlatformIds) {
    var selectedIds = {};
    var i, id;

    // Build a set of selected IDs
    for (i = 0; i < selectedPlatformIds.length; i++) {
        id = String(selectedPlatformIds[i]);
        selectedIds[id] = true;
    }

    var labels = [];
    var consumedIds = {};

    // Add group labels when entire group is selected
    for (var gi = 0; gi < PLATFORM_GROUPS.length; gi++) {
        var groupName = PLATFORM_GROUPS[gi][0];
        var codes = PLATFORM_GROUPS[gi][1];

        // Find platforms matching these codes
        var groupPlatforms = [];
        for (i = 0; i < platforms.length; i++) {
            if (codes.indexOf(platforms[i].code) !== -1) {
                groupPlatforms.push(platforms[i]);
            }
        }

        // Get IDs for group platforms
        var groupIds = [];
        for (i = 0; i < groupPlatforms.length; i++) {
            groupIds.push(String(groupPlatforms[i].id));
        }

        // Find unconsumed IDs in this group
        var unconsumedGroupIds = [];
        for (i = 0; i < groupIds.length; i++) {
            if (!consumedIds[groupIds[i]]) {
                unconsumedGroupIds.push(groupIds[i]);
            }
        }

        // Only match if ALL platforms in group are selected AND none are already consumed
        if (unconsumedGroupIds.length !== 0 && unconsumedGroupIds.length === groupIds.length) {
            var allSelected = true;
            for (i = 0; i < unconsumedGroupIds.length; i++) {
                if (!selectedIds[unconsumedGroupIds[i]]) {
                    allSelected = false;
                    break;
                }
            }

            if (allSelected) {
                labels.push(groupName);
                for (i = 0; i < groupIds.length; i++) {
                    consumedIds[groupIds[i]] = true;
                }
            }
        }
    }

    // Add remaining platform names
    for (id in selectedIds) {
        if (selectedIds.hasOwnProperty(id) && !consumedIds[id]) {
            for (i = 0; i < platforms.length; i++) {
                if (String(platforms[i].id) === id) {
                    labels.push(platforms[i].name);
                    break;
                }
            }
        }
    }

    if (labels.length === 0) return 'Video';
    return joinNames(labels);
}

/**
 * Joins an array of names with proper grammar (commas and "and")
 * @param {Array} names - Array of names to join
 * @returns {string} Joined string
 */
function joinNames(names) {
    if (!names || names.length === 0) return '';
    if (names.length === 1) return names[0];
    if (names.length === 2) return names.join(' and ');
    return names.slice(0, -1).join(', ') + ', and ' + names[names.length - 1];
}

/**
 * Create a throttled scroll handler that updates a boolean based on scroll position.
 * Uses requestAnimationFrame for smooth performance.
 * @param {function} setShow - Callback to set visibility (receives boolean)
 * @param {number} threshold - Scroll threshold in pixels (default 300)
 */
function createScrollShowHandler(setShow, threshold) {
    threshold = threshold || 300;
    var throttled = false;
    window.addEventListener('scroll', function() {
        if (!throttled) {
            throttled = true;
            requestAnimationFrame(function() {
                setShow(window.scrollY > threshold);
                throttled = false;
            });
        }
    });
}

// ============================================================
// HIGHLIGHTING A ROW
// ============================================================

/**
 * Call `callback` once the page has stopped scrolling, or after `maxWait`
 * milliseconds at most. Polled rather than on `scrollend`, which older
 * Safari lacks.
 * @param {Function} callback
 * @param {number} [maxWait=3000]
 */
function whenScrollSettles(callback, maxWait) {
    maxWait = maxWait || 3000;
    var started = Date.now();
    var lastY = window.scrollY;
    var still = 0;
    var check = function() {
        still = window.scrollY === lastY ? still + 1 : 0;
        lastY = window.scrollY;
        if (still >= 2 || Date.now() - started >= maxWait) {
            callback();
            return;
        }
        setTimeout(check, 100);
    };
    setTimeout(check, 100);
}

var HIGHLIGHT_ITEM_SELECTOR = '.game-row, .media-row, .game-card-grid, .media-card-grid';

/**
 * The element the highlight styles apply to. `#game-<id>` and `#music-<id>`
 * are row wrappers, while styles.css colours `.game-row.is-highlighted` and
 * `.media-row.is-highlighted`, so a class on the wrapper showed nothing.
 */
function highlightableElement(el) {
    if (el.matches(HIGHLIGHT_ITEM_SELECTOR)) return el;
    return el.querySelector(HIGHLIGHT_ITEM_SELECTOR) || el;
}

/**
 * Highlight a row (or card) the reader has been sent to, scroll it into
 * view, and fade the highlight once they have seen it.
 *
 * The fade waits for the smooth scroll to finish, so the highlight is still
 * there when the row arrives. Moving the pointer onto another row also fades
 * it, but only a pointer that really moves: rows sliding under a still
 * cursor fire `mouseenter` too. The click that brought the reader here
 * (a genre badge on a detail page, a jump box) leaves the cursor over the
 * list, so the old `mouseenter` listeners faded the highlight before the
 * row had even scrolled into view.
 * @param {Element|null} scrollTarget - Element to scroll to, if any
 * @param {Array<Element|null>} elements - Elements to mark `is-highlighted`
 * @param {Object} [options]
 * @param {number} [options.duration=2500] - How long it stays once arrived
 */
function flashHighlight(scrollTarget, elements, options) {
    var duration = (options && options.duration) || 2500;
    var marked = (elements || []).filter(Boolean).map(highlightableElement);
    if (!marked.length) return;

    marked.forEach(function(el) {
        el.classList.remove('fade-out');
        el.classList.add('is-highlighted');
    });
    if (scrollTarget) {
        scrollTarget.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    var timer = null;
    var origin = null;
    var fade = function() {
        clearTimeout(timer);
        document.removeEventListener('mousemove', onMove);
        marked.forEach(function(el) { el.classList.add('fade-out'); });
    };
    var onMove = function(event) {
        // The first event only fixes where the cursor rests
        if (!origin) {
            origin = { x: event.clientX, y: event.clientY };
            return;
        }
        if (Math.abs(event.clientX - origin.x) + Math.abs(event.clientY - origin.y) < 8) return;
        var item = event.target.closest && event.target.closest(HIGHLIGHT_ITEM_SELECTOR);
        if (!item) return;
        if (marked.some(function(el) { return el === item || el.contains(item) || item.contains(el); })) return;
        fade();
    };

    whenScrollSettles(function() {
        timer = setTimeout(fade, duration);
        document.addEventListener('mousemove', onMove);
    });
}

window.flashHighlight = flashHighlight;

// Signal that utils-base is ready for Alpine
window.utilsBaseReady = true;
// Dispatch event for listeners waiting on utils-base (avoids polling)
window.dispatchEvent(new CustomEvent('utils-base-ready'));
