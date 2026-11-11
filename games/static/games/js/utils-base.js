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
    // An error page is not results: the filter component set the list to
    // whatever came back, so a 500 put the server's error page inside it
    if (!response.ok) {
        throw new Error(`${url} answered ${response.status}`);
    }
    return response.text();
}

/**
 * Replace a Load More container's markup without losing a keyboard
 * reader's place. Enter on Load More replaced the focused button, and focus
 * fell to the top of the page. If focus was inside, it goes to the new
 * button, or, at the end of the list, to the container itself, whose "All N
 * results loaded" is then read out.
 * @param {Element} container
 * @param {string} html
 */
function replaceKeepingFocus(container, html) {
    const hadFocus = container.contains(document.activeElement);
    container.innerHTML = html;
    if (!hadFocus) return;
    const next = container.querySelector('button:not([disabled]), a[href]');
    if (next) {
        next.focus({ preventScroll: true });
        return;
    }
    container.setAttribute('tabindex', '-1');
    container.focus({ preventScroll: true });
}
/**
 * How a scripted scroll should move: 'smooth', or 'auto' for a reader who
 * has asked their system for less motion. The stylesheet already turns
 * `scroll-behavior` off for them, but a script that names `smooth` itself
 * overrides a stylesheet, so each one asks here instead.
 * @returns {string}
 */
function scrollBehavior() {
    const reduced = typeof window.matchMedia === 'function' &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    return reduced ? 'auto' : 'smooth';
}

// ============================================================
// Stored preferences
// ============================================================

/**
 * `localStorage`, or `sessionStorage`, or null when the browser refuses it.
 * With cookies blocked Chrome throws on the property itself, and a private
 * window can refuse a write, so every use goes through the three functions
 * below: a preference that cannot be kept is one that was never set. The
 * games filter component read six of them in its data literal, bare, and
 * never started for such a reader.
 * @param {boolean} [session] - sessionStorage, not localStorage
 */
function webStorage(session) {
    try {
        return session ? window.sessionStorage : window.localStorage;
    } catch (e) {
        return null;
    }
}

/**
 * A stored string, or null if there is none or storage is refused.
 * @param {string} key
 * @param {boolean} [session]
 * @returns {?string}
 */
function readStoredPreference(key, session) {
    if (!key) return null;
    try {
        return webStorage(session).getItem(key);
    } catch (e) {
        return null;
    }
}

/**
 * A stored JSON value, or `fallback` if there is none, it does not parse or
 * storage is refused.
 * @param {string} key
 * @param {*} fallback
 * @param {boolean} [session]
 */
function readStoredJson(key, fallback, session) {
    const stored = readStoredPreference(key, session);
    if (stored === null) return fallback;
    try {
        return JSON.parse(stored);
    } catch (e) {
        return fallback;
    }
}

/**
 * Store a value, if the browser will: over quota or refused, the
 * preference just does not persist.
 * @param {string} key
 * @param {*} value
 * @param {boolean} [session]
 */
function storePreference(key, value, session) {
    if (!key) return;
    try {
        webStorage(session).setItem(key, value);
    } catch (e) {
        // Not kept
    }
}

/**
 * Forget a stored value, if the browser will.
 * @param {string} key
 * @param {boolean} [session]
 */
function removeStoredPreference(key, session) {
    try {
        webStorage(session).removeItem(key);
    } catch (e) {
        // Nothing was kept
    }
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
            // The games rankings' server-rendered filter change lands here
            announceResultCount(element);
        }
    });
}

// ============================================================
// LIVE ANNOUNCEMENTS
// ============================================================

var _announceTimer = null;

/**
 * Says `text` to a screen reader, through the one live region base.html
 * keeps outside every container that is swapped (#live-announcer).
 *
 * A result count sits inside the list a server render replaces, and a live
 * region that arrives with its text already in it is usually not read out;
 * the entity lists' counts (#results-count) were in no live region at all.
 * A count the client renderer rewrites in place is in a region that stayed
 * put, and announces itself: do not call this for those.
 *
 * "Usually": a reader that does read an inserted region heard a rankings
 * count twice, there and here. So the count's markup carries no role, and
 * `markResultCountsLive` gives it one once it is on the page.
 *
 * @param {string} text - What to say; whitespace is collapsed
 */
function announce(text) {
    const region = document.getElementById('live-announcer');
    if (!region) return;
    const message = String(text == null ? '' : text).replace(/\s+/g, ' ').trim();
    clearTimeout(_announceTimer);
    // Emptied first, so the same words twice running are still a change,
    // and filled a moment later, so a burst says only its last
    region.textContent = '';
    if (!message) return;
    _announceTimer = setTimeout(() => {
        region.textContent = message;
    }, 100);
}

/**
 * Announces the result count inside `root`, if it holds one: a rankings
 * page's (the desktop wording, "Showing 100 of 432", whichever is on
 * screen) or an entity list's heading.
 * @param {Element} root - A container the server has just rendered into
 */
function announceResultCount(root) {
    if (!root || typeof root.querySelector !== 'function') return;
    const count = root.querySelector('[data-result-count="desktop"]') ||
        root.querySelector('[data-result-count]') ||
        root.querySelector('#results-count');
    if (count) announce(count.textContent);
    markResultCountsLive(root);
}

/**
 * Makes the rankings' result counts under `root` live regions, now that
 * they are on the page with their text in them: what the client renderer
 * writes into them from here on is read out, and what the server put there
 * was said once, by `announce`.
 * @param {Element|Document} root
 */
function markResultCountsLive(root) {
    if (!root || typeof root.querySelectorAll !== 'function') return;
    root.querySelectorAll('[data-result-count]').forEach((count) => {
        count.setAttribute('role', 'status');
    });
}

// The page's own counts, as it loads: nothing is said of text already there
if (typeof document.querySelectorAll === 'function') {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => markResultCountsLive(document));
    } else {
        markResultCountsLive(document);
    }
}

// An htmx swap that brings a count with it: music's server-side filter
// changes, and the artists and source-lists pages. The engine cancels the
// rankings' requests once it answers them itself, so its renders never get
// here. A Load More that moves an entity list's count sends the new number
// out of band, into a heading that is no live region.
document.addEventListener('htmx:afterSettle', (event) => {
    announceResultCount(event.detail && event.detail.target);
});
document.addEventListener('htmx:oobAfterSwap', (event) => {
    const moved = event.target;
    if (!moved || moved.id !== 'loaded-count' || typeof moved.closest !== 'function') return;
    const heading = moved.closest('#results-count');
    if (heading) announce(heading.textContent);
});

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
 * @returns {URLSearchParams} Built parameters
 */
function buildFilterParams(filters) {
    const params = new URLSearchParams();

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
 * Whether a range covers every year there is. A drag to the last decade's label
 * ends at its 9, past a last year of 2026, so this cannot compare exactly.
 */
function isWholeYearRange(start, end, minYear, maxYear) {
    return !(start > minYear || end < maxYear);
}

/** The heading's time window, as core/services/titles.py builds it. */
function buildTimeWindow(start, end, minYear, maxYear) {
    const unknown = year => year === null || year === undefined || Number.isNaN(year);
    if (unknown(start) || unknown(end)) return '';
    if (isWholeYearRange(start, end, minYear, maxYear)) return 'All Time';
    if (start === end) return String(start);
    if (start % 10 === 0 && end === start + 9) return 'the ' + start + 's';
    const overlaps = end >= minYear && start <= maxYear;
    const first = overlaps ? Math.max(start, minYear) : start;
    const last = overlaps ? Math.min(end, maxYear) : end;
    return first === last ? String(first) : first + '-' + last;
}

/** A tab title's time window, as titles.short_time_window builds it. */
function shortTimeWindow(start, end, minYear, maxYear) {
    const window_ = buildTimeWindow(start, end, minYear, maxYear);
    if (window_ === 'All Time') return '';
    return window_.startsWith('the ') ? window_.slice(4) : window_;
}

/** A filtered page's facet labels for its tab, as titles.short_title joins them. */
function shortTitle(parts) {
    return parts.filter(Boolean).join(' \u00b7 ');
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
    if (isWholeYearRange(start, end, minYear, maxYear)) {
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
 * The query string, plus the filters a page's path implies. Merged rather than
 * used only as a fallback, because a landing URL can still carry ?utm_source=
 * or ?highlight=.
 * @param {string} implied - The path's filters, as a query string
 * @returns {URLSearchParams}
 */
function mergedFilterParams(implied) {
    const params = new URLSearchParams(window.location.search);
    new URLSearchParams(implied || '').forEach((value, key) => {
        if (!params.has(key)) params.set(key, value);
    });
    return params;
}

/**
 * One parameter of an htmx request, from its `requestConfig.parameters`, as
 * the server reads it: htmx 1.9 sends a repeated name as an array, and the
 * server takes the last value.
 * @param {?Object} parameters
 * @param {string} name
 * @returns {string|undefined} undefined when the request did not send it
 */
function htmxParameter(parameters, name) {
    if (!parameters || parameters[name] === undefined || parameters[name] === null) {
        return undefined;
    }
    return String([].concat(parameters[name]).pop());
}

/**
 * The filter params on a page with a landing path: on that bare path, which
 * Back can return to with no query string, the path's own filters count too.
 * @param {string} landingPath - The landing page's path, or '' for none
 * @param {string} landingSearch - What it stands for, as a query string
 * @returns {URLSearchParams}
 */
function landingFilterParams(landingPath, landingSearch) {
    return mergedFilterParams(
        landingPath && window.location.pathname === landingPath ? landingSearch : ''
    );
}

/**
 * The page's filter params: the query string, plus whatever filter a clean
 * SEO path implies. A filter state with its own landing page is pushed as
 * that path (/games/2010s/), with no query string, so anything reading the
 * filters from location.search alone saw none there: jump to rank checked
 * against the whole ranking, and client-rendered rows showed all-time
 * ranks. Old ?year= and ?decade= links, which the server honours, are mapped
 * onto start/end the same way.
 * @param {string} [search] - A query string to read in the page's place: the
 *     one the server rendered a list from (#game-rendered-filters)
 * @returns {URLSearchParams}
 */
function currentFilterParams(search) {
    const params = search === undefined
        ? mergedFilterParams(seoPathSearch(window.location.pathname))
        : new URLSearchParams(search);
    if (!params.get('start') && !params.get('end')) {
        const year = parseInt(params.get('year'));
        const decade = (params.get('decade') || '').match(/^(\d{3}0)-\d{2}$/);
        if (year) {
            params.set('start', year);
            params.set('end', year);
        } else if (decade) {
            params.set('start', decade[1]);
            params.set('end', parseInt(decade[1]) + 9);
        }
    }
    return params;
}

/**
 * Get current filters from the URL, a landing page's path included
 * (currentFilterParams). Reading only the query string, a jump on
 * /games/2010s/ saw no filters: the total was the whole ranking, so rank
 * 500 passed validation and the jump re-rendered the list unfiltered.
 * @param {string} [search] - A query string to read in the page's place
 * @returns {Object} The filters, with null for a year or playtime not given
 */
function getFiltersFromURL(search) {
    const params = currentFilterParams(search);
    // Not a number too: an open-ended playtime is hltb_max=unlimited
    const number = name => {
        const value = parseInt(params.get(name));
        return Number.isFinite(value) ? value : null;
    };
    const list = name => (params.get(name) || '').split(',').filter(id => id);

    return {
        q: params.get('q') || '',
        start: number('start'),
        end: number('end'),
        genres: list('genres'),
        platforms: list('platforms'),
        series: list('series'),
        sort: params.get('sort') || 'rank',
        sortDirection: params.get('dir') || 'asc',
        played: list('played'),
        hltb_mode: params.get('hltb_mode') || 'main',
        hltb_min: number('hltb_min'),
        hltb_max: number('hltb_max')
    };
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
 * Performs unified search API call for developers, games, and series
 * @param {string} query - Search query
 * @param {number} developerLimit - Max developer results
 * @param {number} gameLimit - Max game results
 * @param {number} seriesLimit - Max series results
 * @param {string} apiUrl - API endpoint URL
 * @returns {Promise<Object>} Search results with developers, games, and series arrays
 */
async function searchUnified(query, developerLimit, gameLimit, seriesLimit, apiUrl, signal) {
    const trimmedQuery = query.trim();
    if (trimmedQuery.length < 2) {
        return { developers: [], games: [], series: [], order: null };
    }

    const response = await fetch(
        `${apiUrl}?q=${encodeURIComponent(trimmedQuery)}&developer_limit=${developerLimit}&game_limit=${gameLimit}&series_limit=${seriesLimit}`,
        signal ? { signal } : undefined
    );

    if (!response.ok) {
        throw new Error('API request failed');
    }

    const data = await response.json();
    return {
        developers: data.developers || [],
        games: data.games || [],
        series: data.series || [],
        order: data.order || null
    };
}

/**
 * The groups in the order a search response asks for, known names only.
 *
 * The unified search endpoints put whichever group holds the best match
 * first ("Beatles" leads with the band, "Nintendo" with the developer); the
 * dropdowns loop over this. Anything missing keeps `defaults`' order, so an
 * older cached response without `order` still renders every group. Here,
 * where every page loads it, for games' createUnifiedSearchData below and
 * music's createMediaSearchData (core/js/media-search.js).
 */
function searchGroupOrder(order, defaults) {
    const known = (Array.isArray(order) ? order : [])
        .filter((group, index, all) => defaults.includes(group) && all.indexOf(group) === index);
    return known.concat(defaults.filter(group => !known.includes(group)));
}

// The games search's groups before a response orders them, in the order a
// tie falls: games.api.views.SEARCH_GROUPS, which the response's own
// `order` carries, so this matters only before the first answer.
var SEARCH_GROUPS_GAMES = ['games', 'series', 'developers'];

/**
 * The keyboard half of a search box, spread into each search component: the
 * WAI-ARIA combobox pattern with a listbox popup.
 *
 * The input keeps focus and names the option the arrow keys are on
 * (`aria-activedescendant`); Enter follows it, and with none it does what it
 * always did, the full search. The options are the result links, found in
 * the listbox as it stands (`x-ref="listbox"`), so the groups the template
 * nests them in need no arithmetic here. They stay links, tabbable as
 * before: the arrow keys are a second way in, not the only one.
 *
 * Until 2026-11-10 the boxes were a field followed by links, with no way
 * to them from the field but Tab.
 * @returns {Object} State and methods to spread into an Alpine component
 */
function searchComboboxState() {
    return {
        // The active option's id, or '' for none
        activeOption: '',

        /** @private The result links, in the order shown. */
        _searchOptions() {
            const listbox = this.$refs && this.$refs.listbox;
            return listbox ? Array.from(listbox.querySelectorAll('[role="option"]')) : [];
        },

        /** Moves the active option by `step`, wrapping at either end. */
        moveOption(step) {
            const options = this._searchOptions();
            if (!options.length) {
                this.activeOption = '';
                return;
            }
            const prefix = this.$refs.listbox.id + '-option-';
            let current = -1;
            options.forEach((option, index) => {
                if (option.getAttribute('aria-selected') === 'true') current = index;
                // Numbered afresh each time: a keyed loop reuses elements,
                // so an id given last time may be another position's now
                option.id = prefix + index;
            });
            let next = current + step;
            if (current === -1) next = step > 0 ? 0 : options.length - 1;
            if (next < 0) next = options.length - 1;
            if (next >= options.length) next = 0;
            options.forEach((option, index) => {
                option.setAttribute('aria-selected', index === next ? 'true' : 'false');
            });
            this.activeOption = options[next].id;
            if (typeof options[next].scrollIntoView === 'function') {
                options[next].scrollIntoView({ block: 'nearest' });
            }
        },

        /**
         * Follows the active option, if there is one.
         * @returns {boolean} Whether there was: false leaves Enter to the caller
         */
        activateOption(event) {
            const active = this._searchOptions().find(
                option => option.getAttribute('aria-selected') === 'true'
            );
            if (!active) return false;
            if (event && typeof event.preventDefault === 'function') event.preventDefault();
            active.click();
            return true;
        },

        /** Forgets the active option: the results under it are changing. */
        clearActiveOption() {
            this._searchOptions().forEach(option => option.removeAttribute('aria-selected'));
            this.activeOption = '';
        }
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
    // Only the newest request may write: each one aborts the one before, and
    // an aborted one writes nothing, `loading` included. A slow answer for
    // "ma" used to replace the results for "mario", and emptying the box
    // while a request was out brought its results back. Outside the returned
    // object, so Alpine does not wrap it.
    const requests = new FetchManager();

    return {
        ...searchComboboxState(),
        showMenu: false,
        q: '',
        developers: [],
        games: [],
        series: [],
        order: SEARCH_GROUPS_GAMES.slice(),
        loading: false,
        // The last search failed (an error status, or offline): said as
        // such, where it read as "No results found"
        failed: false,

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
            // The results are about to change under the active option
            this.clearActiveOption();
            const trimmedQ = this.q.trim();
            this.failed = false;
            if (trimmedQ.length < 2) {
                requests.abort();
                this.developers = [];
                this.games = [];
                this.series = [];
                this.loading = false;
                return;
            }
            const signal = requests.newRequest();
            this.loading = true;
            this.developers = [];
            this.games = [];
            this.series = [];
            try {
                const results = await searchUnified(trimmedQ, developerLimit, gameLimit, seriesLimit, apiUrl, signal);
                // Overtaken while it was read: a newer request owns the box
                if (signal.aborted) return;
                this.developers = results.developers;
                this.games = results.games;
                this.series = results.series;
                this.order = searchGroupOrder(results.order, SEARCH_GROUPS_GAMES);
            } catch (e) {
                if (signal.aborted) return;
                console.error('Search error:', e);
                this.developers = [];
                this.games = [];
                this.series = [];
                this.order = SEARCH_GROUPS_GAMES.slice();
                this.failed = true;
            } finally {
                // An aborted request leaves `loading` to whatever replaced it
                if (!signal.aborted) this.loading = false;
            }
        },

        reset() {
            requests.abort();
            this.clearActiveOption();
            this.showMenu = false;
            this.q = '';
            this.developers = [];
            this.games = [];
            this.series = [];
            this.order = SEARCH_GROUPS_GAMES.slice();
            this.loading = false;
            this.failed = false;
        }
    };
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
    ['Nintendo', ['NES', 'SNES', 'N64', 'GC', 'Wii', 'WiiU', 'DS', '3DS', 'SW', 'SW2', 'GB', 'GBA', 'GBC', 'FDS', 'GW']],
    ['PlayStation', ['PS', 'PS2', 'PS3', 'PS4', 'PS5', 'PSP', 'PSV', 'PSVR']],
    ['Sega', ['GEN', 'SMS', 'DC', 'SAT', 'GG', 'SCD']],
    // Other manufacturer groups
    ['Xbox', ['Xbox', 'X360', 'XB1', 'XBXS']],
    ['PC', ['WIN', 'DOS', 'LIN', 'MAC']],
    ['Arcade, Mobile & VR', ['ARC', 'AND', 'iOS', 'LMD', 'VR', 'BR']],
    ['Retro Consoles', ['A26', 'A52', 'A78', 'INTV', 'CV', 'TG16', '3DO', 'NG', 'JAG', 'LYNX', 'NGP', 'VECT', 'WS']],
    ['Microcomputer', ['VC20', 'C64', 'AMI', 'CD32', 'D32', 'MIC', 'ZXS', 'CPC', 'BBCM', 'ARCH', 'PC88', 'PC98', 'FM7', 'FMT', 'SX1', 'MSX', 'A8', 'AST', 'A2', 'TT', 'T80', 'TCC', 'PDP', 'HP21', 'E60']],
    // Form factor groups (checked after manufacturer groups)
    ['Nintendo Handheld', ['GW', 'GB', 'GBC', 'GBA', 'DS', '3DS']],
    ['Nintendo Home Console', ['NES', 'FDS', 'SNES', 'N64', 'GC', 'Wii', 'WiiU', 'SW', 'SW2']],
    ['PlayStation Handheld', ['PSP', 'PSV']],
    ['PlayStation Home Console', ['PS', 'PS2', 'PS3', 'PS4', 'PS5', 'PSVR']],
    ['Sega Handheld', ['GG']],
    ['Sega Home Console', ['SMS', 'GEN', 'SCD', 'SAT', 'DC']],
    // Microcomputer form factor groups
    ['Commodore', ['VC20', 'C64', 'AMI', 'CD32']],
    ['UK Microcomputer', ['ZXS', 'CPC', 'BBCM', 'ARCH', 'D32']],
    ['Japanese Microcomputer', ['PC88', 'PC98', 'FM7', 'FMT', 'SX1', 'MSX', 'TT']],
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
        scrollTarget.scrollIntoView({ behavior: scrollBehavior(), block: 'start' });
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
window.scrollBehavior = scrollBehavior;
window.replaceKeepingFocus = replaceKeepingFocus;
window.readStoredPreference = readStoredPreference;
window.readStoredJson = readStoredJson;
window.storePreference = storePreference;
window.removeStoredPreference = removeStoredPreference;

// Signal that utils-base is ready for Alpine
window.utilsBaseReady = true;
// Dispatch event for listeners waiting on utils-base (avoids polling)
window.dispatchEvent(new CustomEvent('utils-base-ready'));
