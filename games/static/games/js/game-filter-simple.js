/**
 * Acclaimed Games - Hybrid Client-Side Game Filtering
 *
 * Architecture:
 * - Server templates are the single source of truth for rendering
 * - JSON endpoint provides lightweight filter data for fast client-side filtering
 * - HTML preload adds remaining game rows to DOM for pagination
 * - Filtering operates on JSON array, then shows/hides DOM elements by ID
 *
 * This hybrid approach gives:
 * - Fast filtering (JSON is small and quick to fetch/parse)
 * - Single source of truth (only server templates define row rendering)
 * - Instant show/hide once data is loaded
 */

(function() {
    'use strict';

    const PAGE_SIZE = 100;
    const FILTER_DATA_URL = '/api/games/filter-data/';
    const ROWS_PARTIAL_URL = '/games/rows-partial/';

    // State
    let filterDataLoaded = false;
    let rowsPreloaded = false;
    let gamesArray = null;  // Array of game objects from JSON
    let gamesIndex = null;  // Map<gameId, gameObject> for quick lookup

    /**
     * Fetch filter data JSON (lightweight, fast).
     * Called early to enable filtering ASAP.
     */
    async function loadFilterData() {
        if (filterDataLoaded) return gamesArray;

        try {
            const response = await fetch(FILTER_DATA_URL);
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            const data = await response.json();

            // Build arrays and index
            gamesArray = data.games.map(g => ({
                id: g.id,
                year: g.y,
                name: g.n,
                genres: g.g || [],
                platforms: g.p || [],
                series: g.s || [],
                igdbId: g.i,
                rank: g.r
            }));

            gamesIndex = new Map();
            gamesArray.forEach(g => gamesIndex.set(g.id, g));

            filterDataLoaded = true;
            console.log(`[SimpleFilter] Loaded filter data for ${gamesArray.length} games`);

            // Dispatch event for other components
            window.dispatchEvent(new CustomEvent('filter-data-loaded', {
                detail: { count: gamesArray.length }
            }));

            return gamesArray;
        } catch (error) {
            console.error('[SimpleFilter] Failed to load filter data:', error);
            throw error;
        }
    }

    /**
     * Preload all game rows as HTML for DOM presence.
     * This happens after filter data is loaded.
     * Uses batched insertion to avoid blocking the main thread.
     */
    async function preloadGameRows() {
        if (rowsPreloaded) return;

        try {
            const response = await fetch(ROWS_PARTIAL_URL);
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            const html = await response.text();

            const container = document.getElementById('game-list-container');
            if (!container) {
                console.warn('[SimpleFilter] game-list-container not found');
                return;
            }

            // Get existing game IDs
            const existingIds = new Set(
                [...container.querySelectorAll('[data-game-id]')]
                    .map(el => el.dataset.gameId)
            );

            // Parse HTML into rows array
            const temp = document.createElement('div');
            temp.innerHTML = html;

            // Filter to only new rows
            const newRows = [...temp.querySelectorAll('[data-game-id]')]
                .filter(row => !existingIds.has(row.dataset.gameId));

            // Mark as preloaded immediately so filtering knows rows are coming
            rowsPreloaded = true;

            // Insert rows in batches using requestIdleCallback to avoid blocking main thread
            const BATCH_SIZE = 100;
            let index = 0;
            let insertedCount = 0;

            function insertBatch(deadline) {
                // Insert as many rows as we can while there's idle time
                // Use a minimum of 5ms to ensure progress even with short deadlines
                while (index < newRows.length && (deadline.timeRemaining() > 2 || insertedCount % BATCH_SIZE !== 0)) {
                    const row = newRows[index];
                    row.classList.add('preloaded-hidden');
                    container.appendChild(row);
                    insertedCount++;
                    index++;

                    // After each batch, yield to check deadline
                    if (insertedCount % BATCH_SIZE === 0) {
                        break;
                    }
                }

                if (index < newRows.length) {
                    // More rows to insert, schedule next batch
                    requestIdleCallback(insertBatch, { timeout: 1000 });
                } else {
                    // All done
                    console.log(`[SimpleFilter] Preloaded ${insertedCount} additional DOM rows`);
                    window.dispatchEvent(new CustomEvent('games-preload-complete', {
                        detail: { count: insertedCount }
                    }));
                }
            }

            // Start batched insertion
            if (newRows.length > 0) {
                if (typeof requestIdleCallback !== 'undefined') {
                    requestIdleCallback(insertBatch, { timeout: 2000 });
                } else {
                    // Fallback for browsers without requestIdleCallback
                    function insertBatchFallback() {
                        const end = Math.min(index + BATCH_SIZE, newRows.length);
                        while (index < end) {
                            const row = newRows[index];
                            row.classList.add('preloaded-hidden');
                            container.appendChild(row);
                            insertedCount++;
                            index++;
                        }
                        if (index < newRows.length) {
                            setTimeout(insertBatchFallback, 0);
                        } else {
                            console.log(`[SimpleFilter] Preloaded ${insertedCount} additional DOM rows`);
                            window.dispatchEvent(new CustomEvent('games-preload-complete', {
                                detail: { count: insertedCount }
                            }));
                        }
                    }
                    insertBatchFallback();
                }
            } else {
                console.log('[SimpleFilter] No new rows to preload');
                window.dispatchEvent(new CustomEvent('games-preload-complete', {
                    detail: { count: 0 }
                }));
            }
        } catch (error) {
            console.error('[SimpleFilter] Failed to preload rows:', error);
        }
    }

    /**
     * Check if a game matches the current filters.
     * Operates on JSON game object (fast).
     * @param {Object} game - Game object from JSON
     * @param {Object} filters - Filter criteria
     * @param {string} exclude - Optional: exclude this filter type ('year', 'genres', 'platforms', 'series')
     */
    function matchesFilters(game, filters, exclude = null) {
        // Text search (never excluded - always applies)
        if (filters.q && filters.q.trim()) {
            const searchTerm = filters.q.toLowerCase().trim();
            if (!game.name.includes(searchTerm)) {
                return false;
            }
        }

        // Year range (skip if excluded)
        if (exclude !== 'year') {
            if (filters.start && game.year < parseInt(filters.start, 10)) {
                return false;
            }
            if (filters.end && game.year > parseInt(filters.end, 10)) {
                return false;
            }
        }

        // Genre filter (skip if excluded)
        if (exclude !== 'genres' && filters.genres && filters.genres.length > 0) {
            const hasMatch = filters.genres.some(g => game.genres.includes(parseInt(g, 10)));
            if (!hasMatch) return false;
        }

        // Platform filter (skip if excluded)
        if (exclude !== 'platforms' && filters.platforms && filters.platforms.length > 0) {
            const hasMatch = filters.platforms.some(p => game.platforms.includes(parseInt(p, 10)));
            if (!hasMatch) return false;
        }

        // Series filter (skip if excluded)
        if (exclude !== 'series' && filters.series && filters.series.length > 0) {
            const hasMatch = filters.series.some(s => game.series.includes(parseInt(s, 10)));
            if (!hasMatch) return false;
        }

        // Played status filter (never excluded - always applies)
        if (filters.played && window.playedGameIds && game.igdbId) {
            const isPlayed = window.playedGameIds.has(game.igdbId);
            if (filters.played === 'yes' && !isPlayed) return false;
            if (filters.played === 'no' && isPlayed) return false;
        }

        return true;
    }

    /**
     * Apply filters using JSON data, then update DOM visibility.
     * Returns facet counts for filter UI.
     *
     * IMPORTANT: Facet counts use "cross-filtering" - each facet's counts
     * are calculated with its OWN filter excluded. This is standard faceted
     * search behavior so users can see what's available before selecting.
     */
    function applyFilters(filters) {
        if (!filterDataLoaded || !gamesArray) {
            console.warn('[SimpleFilter] Filter data not loaded yet');
            return { total: 0, visible: 0, matchedGames: [], facets: null };
        }

        const yearCounts = {};
        const genreCounts = {};
        const platformCounts = {};
        const seriesCounts = {};

        const matchedGames = [];
        let filteredIndex = 0;

        // Single pass through all games
        for (const game of gamesArray) {
            // Check if game matches ALL filters (for display)
            const matchesAll = matchesFilters(game, filters);

            if (matchesAll) {
                filteredIndex++;
                matchedGames.push({
                    id: game.id,
                    rank: game.rank,
                    index: filteredIndex
                });
            }

            // Year counts: matches all filters EXCEPT year
            if (matchesFilters(game, filters, 'year')) {
                if (game.year) {
                    yearCounts[game.year] = (yearCounts[game.year] || 0) + 1;
                }
            }

            // Genre counts: matches all filters EXCEPT genres
            if (matchesFilters(game, filters, 'genres')) {
                for (const g of game.genres) {
                    genreCounts[g] = (genreCounts[g] || 0) + 1;
                }
            }

            // Platform counts: matches all filters EXCEPT platforms
            if (matchesFilters(game, filters, 'platforms')) {
                for (const p of game.platforms) {
                    platformCounts[p] = (platformCounts[p] || 0) + 1;
                }
            }

            // Series counts: matches all filters EXCEPT series
            if (matchesFilters(game, filters, 'series')) {
                for (const s of game.series) {
                    seriesCounts[s] = (seriesCounts[s] || 0) + 1;
                }
            }
        }

        // Build set of matched IDs for fast DOM lookup
        const matchedIds = new Set(matchedGames.map(g => String(g.id)));

        // Update DOM visibility
        const container = document.getElementById('game-list-container');
        if (container) {
            container.querySelectorAll('[data-game-id]').forEach(row => {
                const gameId = row.dataset.gameId;
                if (matchedIds.has(gameId)) {
                    row.style.display = '';
                    row.classList.remove('preloaded-hidden');
                } else {
                    row.style.display = 'none';
                }
            });
        }

        return {
            total: gamesArray.length,
            visible: matchedGames.length,
            matchedGames,
            facets: {
                years: yearCounts,
                genres: genreCounts,
                platforms: platformCounts,
                series: seriesCounts
            }
        };
    }

    /**
     * Apply pagination by showing only first N visible games.
     */
    function applyPagination(limit = PAGE_SIZE) {
        const container = document.getElementById('game-list-container');
        if (!container) return { shown: 0, total: 0 };

        // Get visible rows grouped by game ID (to handle desktop/mobile pairs)
        const visibleRows = container.querySelectorAll('[data-game-id]:not([style*="display: none"])');
        const gameRows = new Map();

        visibleRows.forEach(row => {
            const gameId = row.dataset.gameId;
            if (!gameRows.has(gameId)) {
                gameRows.set(gameId, []);
            }
            gameRows.get(gameId).push(row);
        });

        // Apply pagination
        let index = 0;
        for (const [gameId, rows] of gameRows) {
            index++;
            if (index > limit) {
                rows.forEach(row => row.classList.add('pagination-hidden'));
            } else {
                rows.forEach(row => row.classList.remove('pagination-hidden'));
            }
        }

        return { shown: Math.min(index, limit), total: gameRows.size };
    }

    /**
     * Show more games beyond current pagination.
     */
    function showMore(additionalCount = PAGE_SIZE) {
        const container = document.getElementById('game-list-container');
        if (!container) return { shown: 0, total: 0, hasMore: false };

        // Find pagination-hidden rows
        const hiddenRows = container.querySelectorAll('[data-game-id].pagination-hidden');
        const gameRows = new Map();

        hiddenRows.forEach(row => {
            const gameId = row.dataset.gameId;
            if (!gameRows.has(gameId)) {
                gameRows.set(gameId, []);
            }
            gameRows.get(gameId).push(row);
        });

        // Show next batch
        let revealed = 0;
        for (const [gameId, rows] of gameRows) {
            if (revealed >= additionalCount) break;
            rows.forEach(row => row.classList.remove('pagination-hidden'));
            revealed++;
        }

        // Count remaining
        const allVisible = container.querySelectorAll('[data-game-id]:not([style*="display: none"])');
        const stillHidden = container.querySelectorAll('[data-game-id].pagination-hidden');

        // Count unique games
        const visibleIds = new Set();
        const shownIds = new Set();

        allVisible.forEach(row => {
            visibleIds.add(row.dataset.gameId);
            if (!row.classList.contains('pagination-hidden')) {
                shownIds.add(row.dataset.gameId);
            }
        });

        return {
            shown: shownIds.size,
            total: visibleIds.size,
            hasMore: stillHidden.length > 0
        };
    }

    /**
     * Get year counts from the full unfiltered dataset.
     * Used to set the baseline for heatmap intensity scaling.
     */
    function getFullYearCounts() {
        if (!filterDataLoaded || !gamesArray) {
            return [];
        }

        const yearCounts = {};
        for (const game of gamesArray) {
            if (game.year) {
                yearCounts[game.year] = (yearCounts[game.year] || 0) + 1;
            }
        }

        // Convert to array format expected by year grid
        return Object.entries(yearCounts)
            .map(([year, count]) => ({ year: parseInt(year, 10), count }))
            .sort((a, b) => a.year - b.year);
    }

    /**
     * Get current visible/shown counts.
     */
    function getVisibleCount() {
        const container = document.getElementById('game-list-container');
        if (!container) return { visible: 0, shown: 0 };

        const allVisible = container.querySelectorAll('[data-game-id]:not([style*="display: none"])');
        const visibleIds = new Set();
        const shownIds = new Set();

        allVisible.forEach(row => {
            visibleIds.add(row.dataset.gameId);
            if (!row.classList.contains('pagination-hidden')) {
                shownIds.add(row.dataset.gameId);
            }
        });

        return {
            visible: visibleIds.size,
            shown: shownIds.size
        };
    }

    // Export API
    window.SimpleGameFilter = {
        loadFilterData,
        preloadGameRows,
        applyFilters,
        applyPagination,
        showMore,
        getVisibleCount,
        getFullYearCounts,
        isFilterDataLoaded: () => filterDataLoaded,
        isPreloaded: () => rowsPreloaded,
        PAGE_SIZE
    };

    // Start loading filter data immediately (it's small and fast)
    loadFilterData().then(() => {
        // After filter data is loaded, preload DOM rows in background
        if (typeof requestIdleCallback !== 'undefined') {
            requestIdleCallback(() => preloadGameRows(), { timeout: 2000 });
        } else {
            setTimeout(preloadGameRows, 500);
        }
    }).catch(err => {
        console.warn('[SimpleFilter] Initial load failed:', err);
    });
})();
