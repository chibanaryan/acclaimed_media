/**
 * Acclaimed Games - Load More Utilities
 *
 * Utilities for progressive loading and "Jump to Rank" functionality.
 * Loaded only after initial page render to avoid blocking.
 */

// Gaming icons for hover effect (from MDI subset)
const LOAD_MORE_ICONS = [
    'mdi-gamepad-variant',
    'mdi-controller',
    'mdi-controller-classic',
    'mdi-pac-man',
    'mdi-space-invaders',
    'mdi-run-fast',
    'mdi-power'
];

/**
 * Track if Load More has been initialized to prevent duplicate event listeners
 */
let loadMoreInitialized = false;

/**
 * Initializes Load More functionality for game search
 * Called after page load and after filter updates
 */
function initLoadMore() {
    const container = document.getElementById('game-results-container');
    if (!container) return;

    // Initialize event delegation once on the container (not the button)
    if (!loadMoreInitialized) {
        // Use event delegation on the container to handle clicks on load-more-button
        container.addEventListener('click', function(e) {
            // Load Previous exists only after a client-side jump, so the
            // bundle is always there to answer it
            if (e.target.closest('.load-previous-button')) {
                handleLoadPreviousCSF();
                return;
            }

            const button = e.target.closest('.load-more-button');
            if (button && !button.classList.contains('is-loading')) {
                // Use CSF load more if available (instant, no network requests)
                if (typeof getClientSideFiltering === 'function') {
                    const csf = getClientSideFiltering();
                    if (csf && csf.isReady()) {
                        handleLoadMoreCSF(csf);
                        return;
                    }
                }
                // Fallback to server-side load more
                handleLoadMore({ currentTarget: button });
            }
        });

        // Use event delegation for hover (icon randomization)
        container.addEventListener('mouseenter', function(e) {
            const button = e.target.closest('.load-more-button');
            if (button) {
                randomizeLoadMoreIcon(button);
            }
        }, true); // Use capture phase to catch mouseenter on button

        loadMoreInitialized = true;
    }

    // Always reinitialize Jump to Rank (it handles its own listener management)
    initJumpToRank();
}

/**
 * Track if Jump to Rank has been initialized
 */
let jumpToRankInitialized = false;

function requestClientFilteringBundle() {
    window.dispatchEvent(new CustomEvent('acclaimed:need-csf'));
}

/**
 * Initializes Jump to Rank functionality using event delegation
 */
function initJumpToRank() {
    if (jumpToRankInitialized) return;

    document.addEventListener('focusin', function(e) {
        if (e.target.classList.contains('jump-to-rank-input')) {
            requestClientFilteringBundle();
        }
    });

    // Use event delegation on document for robustness
    document.addEventListener('click', function(e) {
        if (e.target.closest('.jump-to-rank-btn')) {
            requestClientFilteringBundle();
        }

        const button = e.target.closest('.jump-to-rank-btn');
        if (button) {
            e.preventDefault();
            // Find the associated input (sibling or nearby)
            const container = button.closest('.jump-to-rank-container') ||
                              button.parentElement;
            const input = container?.querySelector('.jump-to-rank-input');
            if (input) {
                handleJumpToRank(input);
            }
        }
    });

    document.addEventListener('keypress', function(e) {
        if (e.key === 'Enter' && e.target.classList.contains('jump-to-rank-input')) {
            requestClientFilteringBundle();
            e.preventDefault();
            handleJumpToRank(e.target);
        }
    });

    jumpToRankInitialized = true;
}

/**
 * Get current filters from URL parameters
 */
function getFiltersFromURL() {
    const params = new URLSearchParams(window.location.search);

    // Parse HLTB parameters
    const hltb_min_str = params.get('hltb_min');
    const hltb_max_str = params.get('hltb_max');
    const hltb_min = hltb_min_str ? parseInt(hltb_min_str) : null;
    const hltb_max = (hltb_max_str && hltb_max_str !== 'unlimited') ? parseInt(hltb_max_str) : null;

    return {
        q: params.get('q') || '',
        start: params.get('start') ? parseInt(params.get('start')) : null,
        end: params.get('end') ? parseInt(params.get('end')) : null,
        genres: params.get('genres') ? params.get('genres').split(',') : [],
        platforms: params.get('platforms') ? params.get('platforms').split(',') : [],
        series: params.get('series') ? params.get('series').split(',') : [],
        sort: params.get('sort') || 'rank',
        sortDirection: params.get('dir') || 'asc',
        played: params.get('played') || '',
        hltb_mode: params.get('hltb_mode') || 'main',
        hltb_min: hltb_min,
        hltb_max: hltb_max
    };
}

/**
 * Get the current game list state from the best available source
 * Priority: CSF renderer state > data attributes > DOM count
 * @returns {Object} { total, loaded, filters, showRank, csf }
 */
function getCurrentState() {
    const filters = getFiltersFromURL();
    let total = 0;
    let loaded = 0;
    let csf = null;

    // Try to get state from CSF (most authoritative when available)
    if (typeof getClientSideFiltering === 'function') {
        csf = getClientSideFiltering();
        if (csf && csf.isReady()) {
            const result = csf.applyFilters(filters);
            if (result) {
                total = result.total;
            }
            // Once the renderer owns the list, how far down it reaches
            if (csf.renderer && csf.renderer.currentItems && csf.renderer.currentItems.length > 0) {
                return {
                    total,
                    loaded: csf.renderer.windowEnd,
                    filters,
                    showRank: hasActiveFilters(filters, csf) ? 'filtered' : 'alltime',
                    csf
                };
            }
        }
    }

    // Still the server's rows, which always start at #1
    if (loaded === 0) {
        const input = document.querySelector('.jump-to-rank-input');
        if (input) {
            loaded = parseInt(input.dataset.loaded) || 0;
            if (total === 0) {
                total = parseInt(input.dataset.total) || 0;
            }
        }
    }

    // Final fallback: count actual rendered rows
    const renderedRows = document.querySelectorAll('#game-list-container .game-row.desktop').length;
    if (renderedRows > loaded) {
        loaded = renderedRows;
    }

    const showRank = hasActiveFilters(filters, csf) ? 'filtered' : 'alltime';

    return { total, loaded, filters, showRank, csf };
}

/**
 * Check if any filters are active (should show filtered rank vs alltime rank)
 * @param {Object} filters - Filters from getFiltersFromURL()
 * @param {Object} csf - ClientSideFiltering instance (optional, for year bounds)
 * @returns {boolean}
 */
function hasActiveFilters(filters, csf) {
    // Check simple filters
    if (filters.q) return true;
    if (filters.genres && filters.genres.length > 0) return true;
    if (filters.platforms && filters.platforms.length > 0) return true;
    if (filters.series && filters.series.length > 0) return true;
    if (filters.played) return true;

    // Check sort - non-default sort or direction counts as filtered
    if (filters.sort && filters.sort !== 'rank') return true;
    if (filters.sortDirection && filters.sortDirection !== 'asc') return true;

    // Check year filter - only active if different from default bounds
    if (csf && csf.getYearBounds) {
        const bounds = csf.getYearBounds();
        if (filters.start && filters.start > bounds.min) return true;
        if (filters.end && filters.end < bounds.max) return true;
    } else {
        // Without CSF, any year value counts as filter
        if (filters.start) return true;
        if (filters.end) return true;
    }

    // Check HLTB filters (only if they narrow the range from defaults)
    // Default range is 0 to ∞, so only filter if min > 0 or max is explicitly set
    if (filters.hltb_min !== null && filters.hltb_min !== undefined && filters.hltb_min > 0) return true;
    if (filters.hltb_max !== null && filters.hltb_max !== undefined) return true;

    return false;
}

/**
 * Wait for the client-side filtering bundle to be ready, briefly.
 *
 * The bundle is requested as soon as a jump box takes focus, so by the time
 * a number has been typed it has almost always arrived.
 * @param {number} timeout - Milliseconds to wait at most
 * @returns {Promise<Object|null>} The ready instance, or null
 */
function waitForClientSideFiltering(timeout) {
    const ready = () => {
        if (typeof getClientSideFiltering !== 'function') return null;
        const csf = getClientSideFiltering();
        return csf && csf.isReady() ? csf : null;
    };
    return new Promise(resolve => {
        const started = Date.now();
        const check = () => {
            const csf = ready();
            if (csf || Date.now() - started >= timeout) {
                resolve(csf);
                return;
            }
            setTimeout(check, 100);
        };
        check();
    });
}

/**
 * Handles jumping to a specific rank
 * @param {HTMLInputElement} input - The rank input element
 */
async function handleJumpToRank(input) {
    requestClientFilteringBundle();

    const targetRank = parseInt(input.value);
    const perPage = parseInt(input.dataset.perPage) || 100;

    // Get authoritative state
    const state = getCurrentState();
    const { total, loaded } = state;

    // Validate input
    if (!targetRank || targetRank < 1 || targetRank > total) {
        input.classList.add('input-error');
        setTimeout(() => input.classList.remove('input-error'), 1000);
        return;
    }

    const csfReady = state.csf && state.csf.isReady();

    // The server's rows start at #1, so anything up to `loaded` is on the
    // page already: no need to wait for the bundle
    if (!csfReady && targetRank <= loaded) {
        scrollToAndHighlightRank(targetRank);
        input.value = '';
        return;
    }

    // Client-side, only the target's neighbourhood is rendered
    const csf = csfReady ? state.csf : await waitForClientSideFiltering(3000);
    if (csf) {
        try {
            jumpToRankClientSide(csf, targetRank);
            input.value = '';
            return;
        } catch (err) {
            console.error('[JumpToRank] Client-side error:', err);
            // Fall through to server-side
        }
    }

    // Fallback: fetch from server (parallel loading). This one still loads
    // every page down to the target, since the server has no Load Previous.
    await jumpToRankServerSide(targetRank, loaded, perPage);
    input.value = '';
}

/**
 * Jump to rank using client-side rendering (instant, no network).
 *
 * Renders the target and JUMP_RADIUS rows either side of it, rather than
 * everything above it, which at rank 4,000 was 8,000 DOM rows. A target
 * already on the page is only scrolled to, and one near the rendered rows
 * extends them; see BaseMediaListRenderer.planJump.
 * @param {Object} csf - The ready ClientSideFiltering instance
 * @param {number} targetRank - 1-based position in the current result set
 */
function jumpToRankClientSide(csf, targetRank) {
    const gameListContainer = document.getElementById('game-list-container');

    if (!gameListContainer) {
        console.error('[JumpToRank CSF] No game list container found');
        return;
    }

    const { filters, showRank, loaded } = getCurrentState();

    // Determine view mode from CSF or container class
    const viewMode = csf.getViewMode ? csf.getViewMode() :
                     (gameListContainer.classList.contains('view-grid') ? 'grid' : 'list');

    // Get filtered games from engine
    const result = csf.applyFilters(filters);
    if (!result || !result.games) {
        console.error('[JumpToRank CSF] No games returned from filter');
        return;
    }

    const renderer = csf.renderer;
    if (renderer.currentItems && renderer.currentItems.length) {
        renderer.currentItems = result.games;
    } else {
        // Taking over the server's rows
        renderer.adopt(result.games, loaded);
    }
    renderer._currentViewMode = viewMode;

    const plan = renderer.planJump(targetRank - 1);
    if (plan.mode !== 'scroll') {
        renderer.showRange(gameListContainer, plan.start, plan.end, { showRank, viewMode });
        csf._hasRenderedUI = true;
    }

    refreshClientLoadMore(csf);

    // Scroll to and highlight the target rank
    setTimeout(() => {
        scrollToAndHighlightRank(targetRank);
    }, 50);
}

/**
 * Redraw the count, Load Previous and Load More from the renderer's window.
 * @param {Object} csf - The ready ClientSideFiltering instance
 */
function refreshClientLoadMore(csf) {
    const gameListContainer = document.getElementById('game-list-container');
    const countContainer = document.querySelector('.result-count');
    const loadMoreContainer = document.querySelector('.load-more-container');

    const state = csf.renderWindowChrome();
    if (loadMoreContainer) {
        loadMoreContainer.innerHTML = csf.renderer.getLoadMoreHtml(state);
        if (state.hasMore) {
            csf._initLoadMoreButton(loadMoreContainer, gameListContainer, countContainer);
        }
    }
}

/**
 * Prepend the page above a jumped-to window (Load Previous).
 */
function handleLoadPreviousCSF() {
    if (typeof getClientSideFiltering !== 'function') return;
    const csf = getClientSideFiltering();
    const gameListContainer = document.getElementById('game-list-container');
    if (!csf || !csf.isReady() || !gameListContainer) return;

    const { showRank } = getCurrentState();
    const restoreScroll = csf.renderer.captureScrollAnchor(gameListContainer);
    csf.renderer.loadPrevious(gameListContainer, { showRank });
    // The button can disappear as well, so keep the place after both
    csf.renderWindowChrome();
    restoreScroll();
}

/**
 * Jump to rank using server-side fetching (fallback)
 */
async function jumpToRankServerSide(targetRank, loaded, perPage) {
    const targetPage = Math.ceil(targetRank / perPage);
    const currentPage = Math.ceil(loaded / perPage);

    // Show loading state on all instances
    const allButtons = document.querySelectorAll('.jump-to-rank-btn');
    const allInputs = document.querySelectorAll('.jump-to-rank-input');
    allButtons.forEach(btn => { btn.classList.add('loading'); btn.disabled = true; });
    allInputs.forEach(inp => { inp.disabled = true; });

    try {
        // Load all pages in parallel for speed
        const pagesToLoad = [];
        for (let page = currentPage + 1; page <= targetPage; page++) {
            pagesToLoad.push(page);
        }

        // Fetch all pages concurrently
        const pageResults = await Promise.all(
            pagesToLoad.map(page => fetchPage(page))
        );

        // Append pages in correct order (they may have arrived out of order)
        pageResults.sort((a, b) => a.page - b.page);
        for (const result of pageResults) {
            appendPageResults(result);
        }

        // Scroll to and highlight the target rank
        setTimeout(() => {
            scrollToAndHighlightRank(targetRank);
        }, 100);
    } catch (err) {
        console.error('Jump to rank error:', err);
    } finally {
        allButtons.forEach(btn => { btn.classList.remove('loading'); btn.disabled = false; });
        allInputs.forEach(inp => { inp.disabled = false; });
    }
}

/**
 * Fetches a specific page and returns parsed results (without appending to DOM)
 * @param {number} page - The page number to load
 * @returns {Promise<{page: number, rows: NodeList, meta: Object}>}
 */
async function fetchPage(page) {
    const params = new URLSearchParams(window.location.search);
    params.set('page', page);
    params.set('append', 'true');

    const url = window.location.pathname + '?' + params.toString();

    const response = await fetch(url, {
        headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'HX-Request': 'true'
        }
    });

    if (!response.ok) throw new Error('Failed to load page ' + page);

    const html = await response.text();
    const parser = new DOMParser();
    const doc = parser.parseFromString(html, 'text/html');

    // Extract metadata
    const metaScript = doc.getElementById('load-more-meta');
    const meta = metaScript ? JSON.parse(metaScript.textContent) : null;

    // Get all game rows (select top-level wrappers, not inner .game-row divs,
    // so desktop rows include the played button container)
    const rows = doc.querySelectorAll('.game-row-wrapper, .game-card-mobile');

    return { page, rows, meta };
}

/**
 * Appends fetched page results to the DOM
 * @param {{page: number, rows: NodeList, meta: Object}} result - Fetched page data
 */
function appendPageResults(result) {
    const { rows, meta } = result;

    // Append game rows
    const gameList = document.getElementById('game-list-container');
    if (gameList) {
        rows.forEach((row) => {
            gameList.appendChild(row);
        });

        // Reinitialize HTMX for dynamically appended content
        if (typeof htmx !== 'undefined') {
            htmx.process(gameList);
        }
    }

    // Update metadata (last page's meta will have final counts)
    if (meta) {
        updateResultSummary(meta.loadedCount, meta.totalCount);

        // Update all jump to rank inputs data
        document.querySelectorAll('.jump-to-rank-input').forEach(input => {
            input.dataset.loaded = meta.loadedCount;
        });

        // Update or remove load more button
        const loadMoreButton = document.querySelector('.load-more-button');
        if (loadMoreButton) {
            updateLoadMoreButton(loadMoreButton, meta);
        }
    }
}

/**
 * Loads a specific page and appends to the list (used by Load More button)
 * @param {number} page - The page number to load
 * @returns {Promise<void>}
 */
async function loadPage(page) {
    const result = await fetchPage(page);
    appendPageResults(result);
}

/**
 * Position of the first rendered row, 0-based: 0 until a jump has rendered
 * a window part-way down the list.
 */
function renderedWindowStart() {
    if (typeof getClientSideFiltering !== 'function') return 0;
    const csf = getClientSideFiltering();
    if (!csf || !csf.isReady() || !csf.renderer) return 0;
    if (!csf.renderer.currentItems || !csf.renderer.currentItems.length) return 0;
    return csf.renderer.windowStart || 0;
}

/**
 * Scrolls to and highlights a specific position in the list
 * @param {number} position - The 1-based position to scroll to (e.g., 50 = 50th game in list)
 */
function scrollToAndHighlightRank(position) {
    // Detect view mode from container. Grid mode shows the list rows until
    // the bundle has built a grid, so the cards count only once one exists.
    const gameListContainer = document.getElementById('game-list-container');
    const isGridView = gameListContainer &&
        gameListContainer.classList.contains('view-grid') &&
        !!gameListContainer.querySelector('.game-grid');

    // Position is 1-based, arrays are 0-based, and after a jump the first
    // rendered row is at windowStart rather than at the top
    const index = position - 1 - renderedWindowStart();

    let elementToScroll = null;
    let elementsToHighlight = [];

    if (isGridView) {
        // Grid view: get grid cards
        const gridCards = document.querySelectorAll('.game-card-grid');
        const gridCard = gridCards[index];
        if (gridCard) {
            elementToScroll = gridCard;
            elementsToHighlight = [gridCard];
        }
    } else {
        // List view: get desktop and mobile rows
        const desktopRows = document.querySelectorAll('.game-row.desktop');
        const mobileRows = document.querySelectorAll('.game-row.game-card-mobile');

        const desktopRow = desktopRows[index];
        const mobileRow = mobileRows[index];

        if (desktopRow || mobileRow) {
            // Find the visible row (desktop rows are hidden on mobile and vice versa)
            elementToScroll = (desktopRow && desktopRow.offsetParent !== null) ? desktopRow :
                              (mobileRow && mobileRow.offsetParent !== null) ? mobileRow :
                              desktopRow || mobileRow;

            if (desktopRow) elementsToHighlight.push(desktopRow);
            if (mobileRow) elementsToHighlight.push(mobileRow);
        }
    }

    if (!elementToScroll) {
        console.warn('Could not find position:', position);
        return;
    }

    flashHighlight(elementToScroll, elementsToHighlight);
}

/**
 * Handles Load More using client-side filtering (instant, no network)
 * @param {ClientSideFiltering} csf - The CSF instance
 */
function handleLoadMoreCSF(csf) {
    const gameListContainer = document.getElementById('game-list-container');
    const loadMoreContainer = document.querySelector('.load-more-container');

    if (!gameListContainer) return;

    // Get authoritative state
    const currentState = getCurrentState();
    const { filters, showRank, loaded } = currentState;

    // Determine view mode from CSF or container class
    const viewMode = csf.getViewMode ? csf.getViewMode() :
                     (gameListContainer.classList.contains('view-grid') ? 'grid' : 'list');

    // Initialize renderer state if not already done (taking over from server-rendered content)
    const renderer = csf.renderer;
    if (!renderer.currentItems || renderer.currentItems.length === 0) {
        // Get the filtered games from the engine
        const result = csf.applyFilters(filters);
        if (!result || !result.games) return;

        // Set the renderer's state based on what's already loaded
        renderer.adopt(result.games, loaded);
    }

    // Ensure renderer knows the current view mode
    renderer._currentViewMode = viewMode;

    // Use CSF's loadMore method
    const state = csf.loadMore(gameListContainer, { showRank });
    if (!state) return;

    // Mark that CSF has taken over
    csf._hasRenderedUI = true;

    // Reinitialize HTMX for dynamically rendered content
    if (typeof htmx !== 'undefined') {
        htmx.process(gameListContainer);
    }

    // Count, Load Previous and the jump boxes
    csf.renderWindowChrome();

    // Update Load More button
    if (loadMoreContainer) {
        loadMoreContainer.innerHTML = csf.renderer.getLoadMoreHtml(state);
    }
}

/**
 * Handles Load More button click
 * @param {Event} event - Click event
 */
async function handleLoadMore(event) {
    const button = event.currentTarget;
    const nextPage = button.dataset.nextPage;

    if (!nextPage || button.classList.contains('is-loading')) return;

    // Set loading state
    button.classList.add('is-loading');
    button.disabled = true;

    // Build URL with current filters + next page + append flag
    const params = new URLSearchParams(window.location.search);
    params.set('page', nextPage);
    params.set('append', 'true');

    const url = window.location.pathname + '?' + params.toString();

    try {
        const response = await fetch(url, {
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'HX-Request': 'true'
            }
        });

        if (!response.ok) throw new Error('Failed to load more');

        const html = await response.text();

        // Parse the response to separate game rows from metadata
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');

        // Extract metadata
        const metaScript = doc.getElementById('load-more-meta');
        const meta = metaScript ? JSON.parse(metaScript.textContent) : null;

        // Remove the metadata script from the parsed doc
        if (metaScript) metaScript.remove();

        // Append game rows without animation (instant load)
        const gameList = document.getElementById('game-list-container');
        if (gameList) {
            const allRows = doc.querySelectorAll('.game-row-wrapper, .game-card-mobile');
            allRows.forEach((row) => {
                gameList.appendChild(row);
            });

            // Reinitialize HTMX for dynamically appended content
            if (typeof htmx !== 'undefined') {
                htmx.process(gameList);
            }
        }

        // Update result summary and button
        if (meta) {
            updateResultSummary(meta.loadedCount, meta.totalCount);
            updateLoadMoreButton(button, meta);
        }

    } catch (err) {
        console.error('Load more error:', err);
        button.classList.remove('is-loading');
        button.disabled = false;
    }
}

/**
 * Randomizes the Load More button icon on hover
 * @param {HTMLElement} button - The Load More button
 */
function randomizeLoadMoreIcon(button) {
    const iconSpan = button.querySelector('.icon .mdi');
    if (iconSpan) {
        // Remove default and all gaming icon classes, then add a random one
        iconSpan.classList.remove('mdi-plus-circle-outline');
        LOAD_MORE_ICONS.forEach(cls => iconSpan.classList.remove(cls));
        const randomIcon = LOAD_MORE_ICONS[Math.floor(Math.random() * LOAD_MORE_ICONS.length)];
        iconSpan.classList.add(randomIcon);
    }
}

/**
 * Updates the result summary text
 * @param {number} loaded - Number of items currently loaded
 * @param {number} total - Total number of items
 */
function updateResultSummary(loaded, total) {
    // Update all loaded count elements (supports multiple instances for responsive layouts)
    document.querySelectorAll('.loaded-count-value, #loaded-count').forEach(el => {
        el.textContent = loaded.toLocaleString();
    });
}

/**
 * Updates the Load More button state based on server response
 * @param {HTMLElement} button - The Load More button
 * @param {Object} meta - Metadata from server response
 */
function updateLoadMoreButton(button, meta) {
    button.classList.remove('is-loading');

    if (!meta.hasMore || meta.maxLoaded) {
        const container = button.parentElement;
        container.innerHTML = `
            <div class="text-base-content/50 text-sm">
                <span class="mdi mdi-check-circle-outline"></span>
                <span>All ${meta.totalCount.toLocaleString()} results loaded</span>
            </div>
        `;
    } else {
        button.disabled = false;
        button.dataset.nextPage = meta.nextPage;
        button.dataset.loaded = meta.loadedCount;

        const textSpan = button.querySelector('.load-more-text');
        if (textSpan) {
            textSpan.textContent = `Load More (${meta.remainingCount.toLocaleString()} remaining)`;
        }
    }
}

/**
 * Jump to a highlighted game by ID using client-side filtering
 * Used when navigating from game detail page with ?highlight=<game_id>
 * @param {number} gameId - The game ID to find and scroll to
 */
function jumpToHighlightedGame(gameId) {
    // Check if game is already loaded in DOM
    var desktopEl = document.getElementById('game-' + gameId);
    var mobileEl = document.getElementById('game-' + gameId + '-mobile');

    if (desktopEl || mobileEl) {
        // Game already loaded - just scroll and highlight
        scrollToAndHighlightGameById(gameId);
        return;
    }

    // Game not loaded - wait for CSF, find position, use jumpToRankClientSide
    var checkCSF = function() {
        if (typeof getClientSideFiltering !== 'function') {
            setTimeout(checkCSF, 100);
            return;
        }

        var csf = getClientSideFiltering();
        if (!csf || !csf.isReady()) {
            setTimeout(checkCSF, 100);
            return;
        }

        // Apply current filters and find the game's position
        var filters = getFiltersFromURL();
        var result = csf.applyFilters(filters);
        if (!result || !result.games) {
            console.warn('[JumpToHighlight] No games in filtered results');
            return;
        }

        // Find the game's position in filtered results (1-based)
        var position = result.games.findIndex(function(g) {
            return g.id === gameId;
        }) + 1;

        if (position <= 0) {
            console.warn('[JumpToHighlight] Game not found in filtered results:', gameId);
            return;
        }

        // Use jumpToRankClientSide directly (same as Jump to Rank)
        jumpToRankClientSide(csf, position);

        // After loading, scroll to the specific game by ID
        setTimeout(function() {
            scrollToAndHighlightGameById(gameId);
        }, 100);
    };

    checkCSF();
}

/**
 * Scroll to and highlight a game by its ID
 * @param {number} gameId - The game ID
 */
function scrollToAndHighlightGameById(gameId) {
    // Detect view mode from container (grid cards exist only once built)
    var gameListContainer = document.getElementById('game-list-container');
    var isGridView = gameListContainer &&
        gameListContainer.classList.contains('view-grid') &&
        !!gameListContainer.querySelector('.game-grid');

    var elementToScroll = null;
    var elementsToHighlight = [];

    if (isGridView) {
        // Grid view: look for grid card
        var gridEl = document.getElementById('game-' + gameId + '-grid');
        if (gridEl) {
            elementToScroll = gridEl;
            elementsToHighlight = [gridEl];
        }
    } else {
        // List view: look for desktop and mobile rows
        var desktopEl = document.getElementById('game-' + gameId);
        var mobileEl = document.getElementById('game-' + gameId + '-mobile');

        var isDesktop = window.matchMedia('(min-width: 962px)').matches;
        elementToScroll = isDesktop ? desktopEl : mobileEl;

        if (desktopEl) elementsToHighlight.push(desktopEl);
        if (mobileEl) elementsToHighlight.push(mobileEl);
    }

    if (elementToScroll) {
        flashHighlight(elementToScroll, elementsToHighlight);
    }
}

// Export for use in templates
window.jumpToHighlightedGame = jumpToHighlightedGame;

// Auto-initialize when script loads
(function() {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initLoadMore);
    } else {
        // DOM already loaded
        initLoadMore();
    }
})();
