/**
 * Acclaimed Games - Filter Component
 *
 * Alpine.js data component for the advanced filters sidebar.
 * Extracted from inline x-data to enable browser caching and reduce main-thread parsing.
 *
 * Usage in template:
 *   <div x-data="filterComponent({ minYear: 1970, maxYear: 2025 })">
 */

// Window flag to prevent duplicate global listener registration (memory leak fix)
// Using window property instead of let to avoid "Identifier already declared" on re-execution
if (typeof window._filterComponentGlobalListenersInitialized === 'undefined') {
    window._filterComponentGlobalListenersInitialized = false;
}

// Explicit cleanup before HTMX swaps to ensure destroy() is called
// (Alpine's destroy hook may not fire reliably during HTMX swaps)
if (typeof window._filterComponentHtmxCleanupInitialized === 'undefined') {
    window._filterComponentHtmxCleanupInitialized = true;
    document.addEventListener('htmx:beforeSwap', (e) => {
        // Check if the swap target contains or is the filter component
        const swapTarget = e.detail.target;
        if (!swapTarget) return;

        const filterEl = swapTarget.matches('[x-data*="filterComponent"]')
            ? swapTarget
            : swapTarget.querySelector('[x-data*="filterComponent"]');

        if (filterEl && typeof Alpine !== 'undefined') {
            const component = Alpine.$data(filterEl);
            if (component && typeof component.destroy === 'function') {
                component.destroy();
            }
        }
    });
}

document.addEventListener('alpine:init', () => {
    Alpine.data('filterComponent', (config) => ({
        // Configuration passed from template
        minYear: config.minYear,
        maxYear: config.maxYear,

        // Data loaded from JSON script tags
        filters: JSON.parse(document.getElementById('filters-data').textContent),
        genres: JSON.parse(document.getElementById('genres-data').textContent),
        platforms: JSON.parse(document.getElementById('platforms-data').textContent),
        seriesList: JSON.parse(document.getElementById('series-data').textContent),

        // Component state
        platformGroupCounts: {},
        initialized: false,
        isLoading: false,
        // Through readStoredPreference: read bare, these threw for a reader
        // whose browser refuses storage, and the component never started
        yearExpanded: readStoredPreference('yearExpanded') !== 'false',
        genresExpanded: readStoredPreference('genresExpanded') !== 'false',
        platformsExpanded: readStoredPreference('platformsExpanded') !== 'false',
        seriesExpanded: readStoredPreference('seriesExpanded') !== 'false',
        hltbExpanded: readStoredPreference('hltbExpanded') !== 'false',
        viewMode: readStoredPreference('gameViewMode') || 'list',
        fetchManager: new FetchManager(),
        _debouncedUpdate: null,
        _debouncedFilter: null,
        _urlFilterKey: '',
        // Moves whenever the URL's filters do: one list's visits apart, so a
        // server page asked for on it before a sort and Back is not taken
        // for this visit's (utils-loadmore.js, serverListKey)
        _urlFilterVisit: 0,
        clientFilterReady: false,
        _clientFilteringInitRequested: false,
        // The engine will not come: its bundle or its data failed
        _clientFilterUnavailable: false,
        // The filters a server request that failed was sent with, until a
        // render succeeds or the controls go back to the list
        _failedFilterKey: null,
        _csf: null,
        // Store listener references for cleanup (memory leak fix)
        _popstateListener: null,
        _gameStatusListener: null,
        _mobileFilterListener: null,
        _needCsfListener: null,

        // Saved filters state
        savedFiltersOpen: false,
        savedFiltersLoading: false,
        savedFilters: [],
        savedFiltersLoaded: false,
        saveFilterModalOpen: false,
        saveFilterName: '',
        saveFilterError: '',
        savedFiltersError: '',
        deleteFilterError: '',
        saveFilterSaving: false,
        applyingSavedFilter: false,
        renameFilterModalOpen: false,
        renameFilterName: '',
        renameFilterError: '',
        renameFilterSaving: false,
        renameFilterTarget: null,
        deleteFilterModalOpen: false,
        deleteFilterTarget: null,
        deleteFilterDeleting: false,

        _getCsrfToken() {
            const name = 'am_csrftoken'; // settings.CSRF_COOKIE_NAME
            let cookieValue = null;
            if (document.cookie && document.cookie !== '') {
                const cookies = document.cookie.split(';');
                for (let i = 0; i < cookies.length; i++) {
                    const cookie = cookies[i].trim();
                    if (cookie.substring(0, name.length + 1) === (name + '=')) {
                        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                        break;
                    }
                }
            }
            return cookieValue;
        },

        // Cleanup method for memory leak prevention
        destroy() {
            if (this._popstateListener) {
                window.removeEventListener('popstate', this._popstateListener);
            }
            if (this._gameStatusListener) {
                window.removeEventListener('game-status-changed', this._gameStatusListener);
            }
            if (this._mobileFilterListener) {
                window.removeEventListener('mobile-filter-opened', this._mobileFilterListener);
            }
            if (this._needCsfListener) {
                window.removeEventListener('acclaimed:need-csf', this._needCsfListener);
            }
            if (this._debouncedFilter) this._debouncedFilter.cancel();
            if (this._debouncedUpdate) this._debouncedUpdate.cancel();
        },

        init() {
            // CRITICAL: Minimal synchronous init - only what's needed for first paint
            if (!this.filters.sort || this.filters.sort === '') {
                this.filters.sort = 'rank';
            }
            if (!this.filters.sortDirection || this.filters.sortDirection === '') {
                this.filters.sortDirection = 'asc';
            }

            const urlParams = new URLSearchParams(window.location.search);
            const highlightParam = urlParams.get('highlight');
            if (highlightParam) {
                this.filters.highlight = highlightParam;
            }
            const dirParam = urlParams.get('dir');
            if (dirParam && (dirParam === 'asc' || dirParam === 'desc')) {
                this.filters.sortDirection = dirParam;
            }
            this._setUrlFilterKey(this._filterKey());

            // Defer non-critical initialization to reduce TBT
            const deferredInit = () => {
                this._debouncedUpdate = debounce(() => this.performUpdate({
                    partial: true, historyMethod: 'pushState'
                }), 300);

                // Leading edge: a click applies at once instead of after
                // 150 ms; a burst still collapses into one trailing update,
                // which replaces the history entry the leading run pushed and
                // is skipped if it would render the same filters again. Only
                // once the client engine is ready: before that the update is
                // a server render, and the old trailing wait is what gives
                // the engine its chance to load first. afterNextPaint lets
                // the click's own feedback paint before the update's work.
                this._debouncedFilter = debounceLeading(burst => this.performUpdate({
                    partial: true,
                    historyMethod: burst.followsLeading ? 'replaceState' : 'pushState'
                }), 150, {
                    canLead: () => this.clientFilterReady,
                    keyOf: () => this._filterKey(),
                    schedule: afterNextPaint
                });

                // Restore scroll position, but not if there's a highlight parameter
                // (highlight scroll will handle positioning in that case)
                const savedScrollPos = readStoredPreference('gameListScrollPos', true);
                const urlParams = new URLSearchParams(window.location.search);
                const hasHighlight = urlParams.has('highlight');
                if (savedScrollPos && !hasHighlight) {
                    setTimeout(() => {
                        window.scrollTo(0, parseInt(savedScrollPos));
                        removeStoredPreference('gameListScrollPos', true);
                    }, 100);
                } else if (savedScrollPos) {
                    // Still clear the saved position even if we're not using it
                    removeStoredPreference('gameListScrollPos', true);
                }

                const saveScrollPosition = () => {
                    storePreference('gameListScrollPos', window.scrollY.toString(), true);
                };

                // Only register global listeners once to prevent memory leaks
                if (!window._filterComponentGlobalListenersInitialized) {
                    window._filterComponentGlobalListenersInitialized = true;

                    document.addEventListener('click', (e) => {
                        const link = e.target.closest("a[href*='/game/']");
                        if (link) {
                            saveScrollPosition();
                        }
                    });

                    // Helper to safely get Alpine component data
                    // Note: There is only ONE filterComponent per page (in the sidebar).
                    // If multiple instances are ever needed, update to querySelectorAll + iterate.
                    const getFilterComponent = () => {
                        const el = document.querySelector('[x-data*="filterComponent"]');
                        return el ? Alpine.$data(el) : null;
                    };

                    document.addEventListener('add-platform', (e) => {
                        const component = getFilterComponent();
                        if (component) component.addPlatform(e.detail);
                    });
                    document.addEventListener('add-platforms', (e) => {
                        const component = getFilterComponent();
                        if (component) component.addPlatforms(e.detail);
                    });
                    document.addEventListener('add-genre', (e) => {
                        const component = getFilterComponent();
                        if (component) component.addGenre(e.detail);
                    });
                    document.addEventListener('add-genres', (e) => {
                        const component = getFilterComponent();
                        if (component) component.addGenres(e.detail);
                    });

                    // Re-dispatch counts after bfcache restoration so platform/genre filters update
                    window.addEventListener('bfcache-restore', () => {
                        // Small delay to ensure all component listeners are set up
                        setTimeout(() => {
                            const component = getFilterComponent();
                            if (component) {
                                // Alpine reinitializes from #filters-data, which may not match
                                // the URL after client-side filtering changed it via pushState.
                                component._syncFiltersFromUrl();

                                if (component.clientFilterReady) {
                                    // Recalculate all counts from cached data (includes HLTB)
                                    component.updateFacetCounts();
                                } else {
                                    // Fall back to server-rendered counts (skip rank distribution
                                    // since the chart preserves correct bins via bfcache)
                                    component.dispatchInitialCounts({ skipRankDistribution: true });
                                }
                            }
                        }, 50);
                    });
                }

                // Store and register instance-specific listeners (cleanup in destroy())
                this._popstateListener = (event) => {
                    // Nothing queued before Back may apply after it.
                    if (this._debouncedFilter) this._debouncedFilter.cancel();
                    if (this._debouncedUpdate) this._debouncedUpdate.cancel();
                    this._syncFiltersFromUrl();
                    // The q watcher below would treat the restored text as a
                    // new search and push it; the update below covers it.
                    this._restoredQuery = this.filters.q;
                    if (this.hasActiveFilters()) {
                        this.requestClientFilteringInit('popstate');
                    }
                    // Re-render for the restored URL without touching history:
                    // the URL is already the one being restored, and pushing
                    // it again cut off the forward history on every Back.
                    if (this.clientFilterReady) {
                        this.performClientUpdate({ historyMethod: null });
                    } else {
                        this.performUpdate({ partial: true, historyMethod: null });
                    }
                };
                window.addEventListener('popstate', this._popstateListener);

                this.$watch('filters.q', val => {
                    if (!this.initialized) return;
                    if (this._restoredQuery !== undefined && val === this._restoredQuery) {
                        this._restoredQuery = undefined;
                        return;
                    }
                    this._restoredQuery = undefined;
                    this.updateResults();
                });

                setTimeout(() => { if (typeof initLoadMore === 'function') initLoadMore(); }, 150);

                this._gameStatusListener = (event) => {
                    if (this.filters.played && this.filters.played.length > 0 && this.clientFilterReady) {
                        this.performClientUpdate({ historyMethod: 'replaceState' });
                    }
                };
                window.addEventListener('game-status-changed', this._gameStatusListener);

                this._mobileFilterListener = () => {
                    if (this.clientFilterReady) {
                        this.updateFacetCounts();
                    } else {
                        this.dispatchInitialCounts();
                    }
                };
                window.addEventListener('mobile-filter-opened', this._mobileFilterListener);

                // utils-loadmore.js asks for the bundle when a jump box takes
                // focus. Loading it is not enough: until this component inits
                // the engine, every jump fell back to fetching each page
                // down to the target from the server.
                this._needCsfListener = () => {
                    this.requestClientFilteringInit('jump-to-rank');
                };
                window.addEventListener('acclaimed:need-csf', this._needCsfListener);

                this.initialized = true;
                this.dispatchInitialCounts();
                if (this.hasActiveFilterParamsOnUrl()) {
                    this.requestClientFilteringInit('initial-url');
                } else if (this.viewMode === 'grid') {
                    // The server renders no grid cards; only the bundle builds them.
                    this.requestClientFilteringInit('grid-view');
                }
            };

            // Use requestIdleCallback to defer non-critical init, fallback to setTimeout
            if ('requestIdleCallback' in window) {
                requestIdleCallback(deferredInit, { timeout: 200 });
            } else {
                setTimeout(deferredInit, 50);
            }
        },

        hasYearFilter() {
            return !isWholeYearRange(
                this.filters.start, this.filters.end, this.minYear, this.maxYear
            );
        },

        hasPlaytimeFilter() {
            return this.filters.hltb_min !== null || this.filters.hltb_max !== null;
        },

        /** What leaves games out of the list: a sort reorders, so it does not count. */
        hasNarrowingFilters() {
            return Boolean(
                this.filters.q ||
                this.filters.genres.length > 0 ||
                this.filters.platforms.length > 0 ||
                (this.filters.series && this.filters.series.length > 0) ||
                this.hasYearFilter() ||
                (this.filters.played && this.filters.played.length > 0) ||
                this.hasPlaytimeFilter()
            );
        },

        hasActiveFilters() {
            return this.hasNarrowingFilters() ||
                   (this.filters.sort && this.filters.sort !== 'rank') ||
                   (this.filters.sortDirection && this.filters.sortDirection !== 'asc');
        },

        hasActiveFilterParamsOnUrl() {
            // Clean SEO paths imply a filter without any search params
            if (!window.location.search &&
                typeof seoPathSearch === 'function' &&
                seoPathSearch(window.location.pathname)) {
                return true;
            }
            const params = new URLSearchParams(window.location.search);
            if (!params.toString()) return false;

            const directKeys = ['highlight', 'q', 'genres', 'platforms', 'series', 'start', 'end', 'sort', 'dir', 'played'];
            for (let i = 0; i < directKeys.length; i++) {
                if (params.has(directKeys[i])) return true;
            }

            for (const [key] of params.entries()) {
                if (key.indexOf('hltb_') === 0) return true;
            }

            return false;
        },

        requestClientFilteringInit(reason = 'interaction') {
            if (this._clientFilteringInitRequested) return;
            this._clientFilteringInitRequested = true;
            this.initClientFiltering();
        },

        async initClientFiltering() {
            // Explicitly request CSF bundle loading from the homepage loader.
            // This keeps default visits lightweight while still allowing on-demand init.
            window.dispatchEvent(new CustomEvent('acclaimed:need-csf'));

            let retries = 0;
            const maxRetries = 30;
            const self = this;

            const doInit = async () => {
                self._csf = getClientSideFiltering();
                try {
                    const started = await self._csf.init({
                        onLoadComplete: () => {
                            self.clientFilterReady = true;
                            self._csf.setViewMode(self.viewMode);
                            // The engine takes over from here: nothing queued
                            // or in flight may repeat this render or undo it.
                            const interrupted = self.isLoading;
                            self.fetchManager.abort();
                            if (interrupted) clearLoading('game-results-container');
                            if (self._debouncedFilter) self._debouncedFilter.cancel();
                            if (self._debouncedUpdate) self._debouncedUpdate.cancel();
                            const changed = self._filterKey() !== self._urlFilterKey;
                            if (changed) {
                                // A change the load overtook. This entry is the
                                // page it left, which Back has to reach.
                                self.performClientUpdate({ historyMethod: 'pushState' });
                            } else if (self.hasActiveFilters()) {
                                self.performClientUpdate({ historyMethod: 'replaceState' });
                            } else if (!self._csf.followsPage()) {
                                // The data is not the version the page was
                                // rendered from, so its rows cannot continue
                                // the page's: they are rendered from it, as
                                // far down as the page had got. The filters
                                // are the URL's, so it stays
                                const shown = document.querySelectorAll(
                                    '#game-list-container .game-row.desktop'
                                ).length;
                                self.performClientUpdate({ historyMethod: null });
                                if (typeof answerLoadMore === 'function') {
                                    answerLoadMore(self._csf, shown);
                                }
                            } else if (interrupted || self._needsClientGrid()) {
                                // The filters are the URL's, so it stays.
                                self.performClientUpdate({ historyMethod: null });
                            } else {
                                self.updateFacetCounts();
                            }
                        }
                    });
                    // init() answers false, not an error, when the data
                    // would not load
                    if (!started) self._engineUnavailable();
                } catch (e) {
                    console.error('[CSF] Failed to initialize:', e);
                    self.dispatchInitialCounts();
                    self._engineUnavailable();
                }
            };

            const tryInit = () => {
                if (typeof getClientSideFiltering !== 'function') {
                    retries++;
                    if (retries < maxRetries) {
                        setTimeout(tryInit, 100);
                        return;
                    }
                    self.dispatchInitialCounts();
                    self._engineUnavailable();
                    return;
                }

                if ('requestIdleCallback' in window) {
                    requestIdleCallback(doInit);
                } else {
                    setTimeout(doInit, 50);
                }
            };

            tryInit();
        },

        /** The engine will not answer: its bundle or its data failed. */
        _engineUnavailable() {
            this._clientFilterUnavailable = true;
            this._rollBackIfStranded();
        },

        /**
         * Put the controls back on the filters the list was rendered with,
         * when a server filter request has failed and no engine is coming
         * to render the ones asked for. They were left as asked: the year
         * grid on a decade over a list that still showed every year.
         *
         * The list's filters are its own echo of the request
         * (#game-rendered-filters), read as the URL is on Back. The
         * heading, the tab and the address were never moved, since only a
         * render moves them, so the controls are all there is to undo. The
         * click is lost, and nothing claims a filter the list does not show.
         *
         * Not while the engine may still come: once it has its data it
         * renders the filters asked for, which the URL lacks, and pushes
         * them. And not once the reader has changed something since the
         * request was sent: that change is queued or on its way, and is
         * theirs to keep.
         */
        _rollBackIfStranded() {
            const failed = this._failedFilterKey;
            if (failed === null || this.clientFilterReady) return;
            if (this._clientFilteringInitRequested && !this._clientFilterUnavailable) return;
            this._failedFilterKey = null;
            if (this._filterKey() !== failed) return;
            const echo = document.getElementById('game-rendered-filters');
            if (!echo) return;
            const typed = this.filters.q;
            this._syncFiltersFromUrl(echo.dataset.query || '');
            // The q watcher would send the restored text as a new search
            if (this.filters.q !== typed) this._restoredQuery = this.filters.q;
        },

        async loadSavedFilters() {
            if (this.savedFiltersLoading) return;
            this.savedFiltersOpen = true;
            if (this.savedFiltersLoaded) return;

            this.savedFiltersLoading = true;
            this.savedFiltersError = '';
            try {
                const response = await fetch('/api/saved-filters/');
                if (response.ok) {
                    const data = await response.json();
                    this.savedFilters = data.filter_sets || [];
                    this.savedFiltersLoaded = true;
                } else {
                    // The menu opened on nothing, with no word of why
                    this.savedFiltersError = 'Saved filters could not be loaded.';
                }
            } catch (e) {
                this.savedFiltersError = 'Saved filters could not be loaded.';
                console.error('[SavedFilters] Failed to load:', e);
            } finally {
                this.savedFiltersLoading = false;
            }
        },

        applySavedFilter(filter) {
            this.applyingSavedFilter = true;
            const f = filter.filters;
            this.filters.q = f.q || '';
            this.filters.start = f.start || this.minYear;
            this.filters.end = f.end || this.maxYear;
            this.filters.genres = f.genres || [];
            this.filters.platforms = f.platforms || [];
            this.filters.series = f.series || [];
            this.filters.sort = f.sort || 'rank';
            // `submitSaveFilter` has always stored this; nothing read it
            // back, so applying a saved filter dropped its direction.
            this.filters.sortDirection = f.sortDirection || 'asc';
            this.filters.played = Array.isArray(f.played) ? f.played : (f.played ? f.played.split(',').filter(s => s) : []);
            this.filters.hltb_mode = f.hltb_mode || 'main';
            this.filters.hltb_min = f.hltb_min || null;
            this.filters.hltb_max = f.hltb_max || null;
            this.filters.hltb_preset = this.calculateHltbPreset(this.filters.hltb_min, this.filters.hltb_max);
            this.savedFiltersOpen = false;
            this.requestClientFilteringInit('saved-filter');
            this.debouncedFilterUpdate();

            const resetFlag = () => {
                this.applyingSavedFilter = false;
                document.removeEventListener('htmx:afterSwap', resetFlag);
            };
            document.addEventListener('htmx:afterSwap', resetFlag, { once: true });
            setTimeout(() => { this.applyingSavedFilter = false; }, 500);
        },

        saveCurrentFilters() {
            this.saveFilterName = this._buildDynamicTitle();
            this.saveFilterError = '';
            this.saveFilterSaving = false;
            this.saveFilterModalOpen = true;
            this.savedFiltersOpen = false;
            this.$nextTick(() => {
                const input = document.getElementById('save-filter-name-input');
                if (input) {
                    input.focus();
                    input.select();
                }
            });
        },

        async submitSaveFilter() {
            const name = this.saveFilterName.trim();
            if (!name) {
                this.saveFilterError = 'Filter name is required';
                return;
            }
            if (name.length > 255) {
                this.saveFilterError = 'Filter name must be 255 characters or less';
                return;
            }

            this.saveFilterSaving = true;
            this.saveFilterError = '';

            const csrfToken = this._getCsrfToken();
            try {
                const response = await fetch('/api/saved-filters/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken,
                    },
                    body: JSON.stringify({
                        name: name,
                        filters: {
                            q: this.filters.q,
                            start: this.filters.start,
                            end: this.filters.end,
                            genres: this.filters.genres,
                            platforms: this.filters.platforms,
                            series: this.filters.series,
                            sort: this.filters.sort,
                            sortDirection: this.filters.sortDirection,
                            played: this.filters.played,
                            hltb_mode: this.filters.hltb_mode,
                            hltb_min: this.filters.hltb_min,
                            hltb_max: this.filters.hltb_max,
                        },
                    }),
                });

                if (response.ok) {
                    const newFilter = await response.json();
                    this.savedFilters.unshift(newFilter);
                    this.saveFilterModalOpen = false;
                } else {
                    let errorMsg = 'Failed to save filter';
                    try {
                        const error = await response.json();
                        errorMsg = error.error || errorMsg;
                    } catch (e) {
                        errorMsg = 'Error ' + response.status + ': ' + response.statusText;
                    }
                    this.saveFilterError = errorMsg;
                }
            } catch (e) {
                console.error('[SavedFilters] Failed to save:', e);
                this.saveFilterError = 'Network error - please try again';
            } finally {
                this.saveFilterSaving = false;
            }
        },

        renameSavedFilter(filter) {
            this.renameFilterTarget = filter;
            this.renameFilterName = filter.name;
            this.renameFilterError = '';
            this.renameFilterSaving = false;
            this.renameFilterModalOpen = true;
            this.savedFiltersOpen = false;
            this.$nextTick(() => {
                const input = document.getElementById('rename-filter-name-input');
                if (input) {
                    input.focus();
                    input.select();
                }
            });
        },

        async submitRenameFilter() {
            const name = this.renameFilterName.trim();
            if (!name) {
                this.renameFilterError = 'Filter name is required';
                return;
            }
            if (name === this.renameFilterTarget.name) {
                this.renameFilterModalOpen = false;
                return;
            }

            this.renameFilterSaving = true;
            this.renameFilterError = '';

            const csrfToken = this._getCsrfToken();
            try {
                const response = await fetch('/api/saved-filters/' + this.renameFilterTarget.id + '/', {
                    method: 'PATCH',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken,
                    },
                    body: JSON.stringify({ name: name }),
                });

                if (response.ok) {
                    this.renameFilterTarget.name = name;
                    this.renameFilterModalOpen = false;
                } else {
                    let errorMsg = 'Failed to rename filter';
                    try {
                        const error = await response.json();
                        errorMsg = error.error || errorMsg;
                    } catch (e) {
                        errorMsg = 'Error ' + response.status + ': ' + response.statusText;
                    }
                    this.renameFilterError = errorMsg;
                }
            } catch (e) {
                console.error('[SavedFilters] Failed to rename:', e);
                this.renameFilterError = 'Network error - please try again';
            } finally {
                this.renameFilterSaving = false;
            }
        },

        deleteSavedFilter(filter) {
            this.deleteFilterTarget = filter;
            this.deleteFilterDeleting = false;
            this.deleteFilterError = '';
            this.deleteFilterModalOpen = true;
            this.savedFiltersOpen = false;
        },

        async confirmDeleteFilter() {
            this.deleteFilterDeleting = true;
            this.deleteFilterError = '';
            const csrfToken = this._getCsrfToken();
            try {
                const response = await fetch('/api/saved-filters/' + this.deleteFilterTarget.id + '/', {
                    method: 'DELETE',
                    headers: { 'X-CSRFToken': csrfToken },
                });

                if (response.ok) {
                    const index = this.savedFilters.indexOf(this.deleteFilterTarget);
                    if (index > -1) this.savedFilters.splice(index, 1);
                    this.deleteFilterModalOpen = false;
                } else {
                    this.deleteFilterError = 'This filter could not be deleted.';
                }
            } catch (e) {
                this.deleteFilterError = 'This filter could not be deleted.';
                console.error('[SavedFilters] Failed to delete:', e);
            } finally {
                this.deleteFilterDeleting = false;
            }
        },

        /** The playtime range as the heading names it, as `_playtime_label` does. */
        _playtimeLabel() {
            const min = this.filters.hltb_min;
            const max = this.filters.hltb_max;
            if (min === null && max === null) return '';
            const mode = this.filters.hltb_mode || 'main';
            const modeSuffix = mode === 'completionist' ? ' (100%)' : '';
            let timeDesc = '';

            if (min === 0 && max === 10) {
                timeDesc = 'Short (<10 Hour)';
            } else if (min === 10 && max === 30) {
                timeDesc = 'Medium (10-30 Hour)';
            } else if (min === 30 && max === null) {
                timeDesc = 'Long (30+ Hour)';
            } else if (min === 0 && max !== null) {
                timeDesc = '<' + max + ' Hour';
            } else if (min !== null && max !== null) {
                if (min === max) {
                    timeDesc = '~' + min + ' Hour';
                } else {
                    timeDesc = min + '-' + max + ' Hour';
                }
            } else if (min !== null) {
                timeDesc = min + '+ Hour';
            } else if (max !== null) {
                timeDesc = '<' + max + ' Hour';
            }
            return timeDesc ? timeDesc + modeSuffix : '';
        },

        /** The played filter's statuses, as `_played_label` names them. */
        _playedLabel() {
            const played = this.filters.played;
            // A string is the pre-array form of the same comma-joined values
            const chosen = Array.isArray(played)
                ? played
                : String(played || '').split(',');
            return [['yes', 'Played'], ['want', 'Want to Play'], ['no', 'Untracked']]
                .filter(([value]) => chosen.includes(value))
                .map(([, title]) => title)
                .join(' + ');
        },

        _selectedGenreNames() {
            return (this.filters.genres || [])
                .map(gid => this.genres.find(g => String(g.id) === String(gid)))
                .filter(g => g)
                .map(g => g.name);
        },

        /** The series' name when exactly one is selected, which is when titles name it. */
        _selectedSeriesName() {
            if (!this.filters.series || this.filters.series.length !== 1) return '';
            const series = this.seriesList.find(s => String(s.id) === String(this.filters.series[0]));
            return series ? series.name : '';
        },

        _buildDynamicTitle() {
            const timeWindow = buildTimeWindow(
                this.filters.start, this.filters.end, this.minYear, this.maxYear
            );
            const genreNames = this._selectedGenreNames();
            const genreLabel = genreNames.length ? ' ' + this._joinNames(genreNames) : '';
            const seriesLabel = this._selectedSeriesName();
            const hltbLabel = this._playtimeLabel();

            const timeSuffix = timeWindow ? ' of ' + timeWindow : '';
            let platform = this._buildPlatformSegment();

            if ((genreLabel || seriesLabel || hltbLabel) && platform === 'Video') {
                platform = '';
            }

            let titleParts = 'Most Acclaimed';
            if (hltbLabel) titleParts += ' ' + hltbLabel;
            if (platform) titleParts += ' ' + platform;
            if (genreLabel) titleParts += genreLabel;
            if (seriesLabel) titleParts += ' ' + seriesLabel;
            titleParts += ' Games' + timeSuffix;

            const played = this._playedLabel();
            if (played) titleParts += ': ' + played;

            return titleParts;
        },

        /**
         * A filtered page's tab title without its suffix, or '' when nothing
         * filters. Mirrors `games.views.filter_titles._build_tab_title`.
         */
        _buildTabTitle() {
            const query = this.filters.q || '';
            const platform = this._buildPlatformSegment();
            return shortTitle([
                query ? '\u201c' + query + '\u201d' : '',
                this._playtimeLabel(),
                platform === 'Video' ? '' : platform,
                this._joinNames(this._selectedGenreNames()),
                this._selectedSeriesName(),
                shortTimeWindow(
                    this.filters.start, this.filters.end, this.minYear, this.maxYear
                ),
                this._playedLabel()
            ]);
        },

        /**
         * The document title a reload of the URL these filters go to would
         * give: the facets, unless that URL is a landing page (`_filterUrl`
         * pushes /games/1990s/ for the 1990s) or nothing filters, when it is
         * the heading. Nothing is kept from the page's load: a title
         * remembered for "the state the page was served for" came back for
         * any state with the same facets, whatever URL it went to.
         */
        _documentTitle(heading) {
            const tabTitle = this._buildTabTitle();
            const url = this._filterUrl();
            const landing = url.startsWith('/games/') && !url.includes('?');
            if (tabTitle && !landing) return tabTitle + (window.tabTitleSuffix || '');
            return heading + window.documentTitleSuffix;
        },

        _buildPlatformSegment() {
            return buildPlatformSegment(this.platforms, this.filters.platforms);
        },

        _joinNames(names) {
            if (!names || names.length === 0) return '';
            if (names.length === 1) return names[0];
            if (names.length === 2) return names.join(' and ');
            return names.slice(0, -1).join(', ') + ', and ' + names[names.length - 1];
        },

        handleFilterChange(type, data) {
            if (type === 'hltb' && data.modeOnly && this.initialized) {
                // Only the mode changed. With no playtime range or playtime sort,
                // the result set and order are unchanged, so swap the displayed
                // times in place instead of re-filtering.
                if (!this._resultsDependOnHltbMode()) {
                    this.applyPlaytimeMode(data.mode);
                    return;
                }
                // Results change: update right away (a click needs no debounce)
                this.requestClientFilteringInit('filter-change');
                this.performUpdate({ partial: true, historyMethod: 'pushState' });
                return;
            }
            if (type === 'hltb') {
                this.filters.hltb_mode = data.mode;
                this.filters.hltb_min = data.min;
                this.filters.hltb_max = data.max;
                this.filters.hltb_preset = this.calculateHltbPreset(data.min, data.max);
            } else {
                const itemIds = data.map(item => {
                    if (typeof item === 'object' && item !== null && item.id !== undefined) {
                        return String(item.id);
                    }
                    return String(item);
                });
                if (type === 'genres') {
                    this.filters.genres = itemIds;
                } else if (type === 'platforms') {
                    this.filters.platforms = itemIds;
                } else if (type === 'series') {
                    this.filters.series = itemIds;
                }
            }
            if (this.initialized) {
                this.debouncedFilterUpdate();
            }
        },

        _resultsDependOnHltbMode() {
            return this.hasPlaytimeFilter() || this.filters.sort === 'playtime';
        },

        /**
         * Switch displayed playtimes between Main and 100% without re-filtering.
         * Rows carry both formatted times in data-playtime-* attributes
         * (see _game_row_*.html and game-list-renderer.js).
         */
        applyPlaytimeMode(mode) {
            const completionist = mode === 'completionist';
            if (this._csf && this._csf.renderer) {
                // Rows rendered later (Load More, Jump to Rank) use the same mode
                this._csf.renderer.hltbMode = mode;
            }
            document.querySelectorAll('[data-slot="playtime"][data-playtime-title]').forEach(el => {
                const text = completionist ? el.dataset.playtimeCompletionist : el.dataset.playtimeMain;
                el.textContent = text || '';
                el.title = completionist ? `${el.dataset.playtimeTitle} (100%)` : el.dataset.playtimeTitle;
                // Grid cards hide the element itself; list rows hide the meta-row item
                const item = el.classList.contains('game-card-playtime') ? el : el.parentElement;
                item.classList.toggle('hidden', !text);
            });
            this._writeHistory('pushState', this._filterUrl());
        },

        /**
         * Download the list as filtered. From a button: a link's address is
         * one a scraper collects, and every one it asked for was a file
         * rendered. A navigation all the same, which every browser, in-app
         * ones included, knows to save: the file is an attachment, so the
         * page stays. Without the highlight, which is where the reader landed
         * and no filter, and without a year range that is all of them.
         * @param {string} url - The download view's address
         */
        downloadCsv(url) {
            const params = buildFilterParams(this.filters);
            params.delete('highlight');
            if (!this.hasYearFilter()) {
                params.delete('start');
                params.delete('end');
            }
            const query = normalizeUrl(params.toString());
            window.location.assign(query ? url + '?' + query : url);
        },

        _filterUrl() {
            const params = buildFilterParams(this.filters);
            // The whole year range is no year filter, so it stays out of the
            // address: every filtered URL used to carry start=1971&end=2025,
            // and clearing a year left the visitor on /games/?start=...
            if (!this.hasYearFilter()) {
                params.delete('start');
                params.delete('end');
            }
            const query = normalizeUrl(params.toString());
            // Prefer the clean SEO page URL when this filter state has one;
            // no filters at all is the home page (/games/ is the browse index)
            return (typeof seoCleanUrl === 'function' &&
                seoCleanUrl(params, this.minYear, this.maxYear)) ||
                (query ? '/games/?' + query : '/');
        },

        /**
         * Read the filters back from the URL, which they then match, or
         * from `search`, the query a list was rendered from, on a page whose
         * URL is that list's.
         */
        _syncFiltersFromUrl(search) {
            const url = getFiltersFromURL(search);
            Object.assign(this.filters, url, {
                start: url.start === null ? this.minYear : url.start,
                end: url.end === null ? this.maxYear : url.end,
                hltb_preset: this.calculateHltbPreset(url.hltb_min, url.hltb_max)
            });
            this._setUrlFilterKey(this._filterKey());
        },

        /** Record the filters the URL now holds, and a new visit if they moved. */
        _setUrlFilterKey(key) {
            if (key !== this._urlFilterKey) this._urlFilterVisit += 1;
            this._urlFilterKey = key;
        },

        /** The filters as one value. A highlight is spent by the first update. */
        _filterKey() {
            const params = buildFilterParams(this.filters);
            params.delete('highlight');
            return params.toString();
        },

        /**
         * Every URL write, so that the engine can tell what reached the URL.
         * A push of the filters the URL already holds replaces it instead:
         * Clear All from a jumped list re-renders the same filters, and pushed
         * `/` over `/`. Not skipped, since the URL may still carry a highlight.
         */
        _writeHistory(method, url, key = this._filterKey()) {
            if (method === 'pushState' && key === this._urlFilterKey) {
                method = 'replaceState';
            }
            window.history[method]({}, '', url);
            this._setUrlFilterKey(key);
        },

        resetSearch() {
            this.filters.q = '';
            if (this.initialized) this.updateResults();
        },

        resetYears() {
            this.filters.start = this.minYear;
            this.filters.end = this.maxYear;
            if (this.initialized) this.debouncedFilterUpdate();
        },

        resetPlatforms() {
            this.filters.platforms = [];
            this.$dispatch('platforms-reset');
            if (this.initialized) this.debouncedFilterUpdate();
        },

        resetGenres() {
            this.filters.genres = [];
            this.$dispatch('genres-reset');
            if (this.initialized) this.debouncedFilterUpdate();
        },

        resetSeries() {
            this.filters.series = [];
            this.$dispatch('series-reset');
            if (this.initialized) this.debouncedFilterUpdate();
        },

        calculateHltbPreset(min, max) {
            if (min === null && max === null) return '';
            if (min === 0 && max === 10) return 'short';
            if (min === 10 && max === 30) return 'medium';
            if (min === 30 && max === null) return 'long';
            return 'custom';
        },

        resetHltb() {
            this.filters.hltb_mode = 'main';
            this.filters.hltb_preset = '';
            this.filters.hltb_min = null;
            this.filters.hltb_max = null;
            window.dispatchEvent(new CustomEvent('hltb-reset'));
            if (this.initialized) this.debouncedFilterUpdate();
        },

        /**
         * Add or remove one value of a multi-select status filter, and
         * clear one. The method names core/includes/_status_filter.html
         * calls, shared with music's mediaListControls; `key` is 'played'.
         */
        toggleStatusValue(key, value) {
            const current = Array.isArray(this.filters[key]) ? this.filters[key] : [];
            this.filters[key] = current.includes(value)
                ? current.filter(s => s !== value)
                : [...current, value];
            if (this.initialized) this.debouncedFilterUpdate();
        },

        resetStatus(key) {
            this.filters[key] = [];
            if (this.initialized) this.debouncedFilterUpdate();
        },

        resetAllFilters() {
            this.filters.q = '';
            this.filters.start = this.minYear;
            this.filters.end = this.maxYear;
            this.filters.genres = [];
            this.filters.platforms = [];
            this.filters.series = [];
            this.filters.played = [];
            this.filters.sort = 'rank';
            this.filters.sortDirection = 'asc';
            this.filters.hltb_mode = 'main';
            this.filters.hltb_preset = '';
            this.filters.hltb_min = null;
            this.filters.hltb_max = null;
            this.$dispatch('platforms-reset');
            this.$dispatch('genres-reset');
            this.$dispatch('series-reset');
            window.dispatchEvent(new CustomEvent('hltb-reset'));
            if (this.initialized) this.debouncedFilterUpdate();
            window.scrollTo({ top: 0, behavior: scrollBehavior() });
        },

        addPlatform(data) {
            const { platformId, gameId } = data;
            const id = String(platformId);
            this.filters.q = '';
            this.filters.start = this.minYear;
            this.filters.end = this.maxYear;
            this.filters.genres = [];
            this.filters.platforms = [id];
            this.$dispatch('genres-reset');
            if (this.initialized) this.debouncedFilterUpdate();
            window.scrollTo({ top: 0, behavior: scrollBehavior() });
        },

        addPlatforms(data) {
            const { platformIds, gameId } = data;
            const ids = platformIds.split(',').filter(id => id);
            this.filters.q = '';
            this.filters.start = this.minYear;
            this.filters.end = this.maxYear;
            this.filters.genres = [];
            this.filters.platforms = ids;
            this.$dispatch('genres-reset');
            if (this.initialized) this.debouncedFilterUpdate();
            window.scrollTo({ top: 0, behavior: scrollBehavior() });
        },

        addGenre(data) {
            const { genreId, gameId } = data;
            const id = String(genreId);
            this.filters.q = '';
            this.filters.start = this.minYear;
            this.filters.end = this.maxYear;
            this.filters.genres = [id];
            this.filters.platforms = [];
            this.$dispatch('platforms-reset');
            if (this.initialized) this.debouncedFilterUpdate();
            window.scrollTo({ top: 0, behavior: scrollBehavior() });
        },

        addGenres(data) {
            const { genreIds, gameId } = data;
            const ids = genreIds.split(',').filter(id => id);
            this.filters.q = '';
            this.filters.start = this.minYear;
            this.filters.end = this.maxYear;
            this.filters.genres = ids;
            this.filters.platforms = [];
            this.$dispatch('platforms-reset');
            if (this.initialized) this.debouncedFilterUpdate();
            window.scrollTo({ top: 0, behavior: scrollBehavior() });
        },

        async performUpdate(options = {}) {
            const { partial = false, historyMethod = 'pushState' } = options;

            if (this.clientFilterReady) {
                return this.performClientUpdate({ historyMethod });
            }

            const signal = this.fetchManager.newRequest();
            const filterKey = this._filterKey();
            this.isLoading = true;
            setLoading('game-results-container');

            const params = buildFilterParams(this.filters);
            // The address the list is asked for at, and (below) the one the
            // reader is shown, which keeps its `/games/?` spelling: Back and
            // the landing pages read that shape. Fetching it was a redirect
            // to `/?...` on every server-side filter change.
            const query = normalizeUrl(params.toString());
            const url = '/games/?' + query;

            try {
                const html = await fetchHtml('/?' + query, signal);

                if (partial) {
                    const content = parseAndExtract(html, [
                        { selector: '#search-heading', targetId: 'search-heading' },
                        { selector: '#game-results-container', targetId: 'game-results-container' }
                    ]);
                    updateDomElements(content);
                    if (typeof window.initRankDistributionCharts === 'function') {
                        window.initRankDistributionCharts();
                    } else {
                        window.dispatchEvent(new CustomEvent('rank-distribution-init'));
                    }
                    if (typeof initLoadMore === 'function') initLoadMore();

                    const urlParams = new URLSearchParams(params.toString());
                    const highlightId = urlParams.get('highlight');
                    if (highlightId) {
                        setTimeout(() => {
                            const desktopElement = document.getElementById('game-' + highlightId);
                            const mobileElement = document.getElementById('game-' + highlightId + '-mobile');
                            const isDesktop = window.matchMedia('(min-width: 962px)').matches;
                            const element = isDesktop ? desktopElement : mobileElement;

                            if (element) {
                                flashHighlight(element, [desktopElement, mobileElement]);
                            }
                        }, 300);
                    }

                    const yearCountsEl = document.getElementById('year-counts-update');
                    if (yearCountsEl) {
                        try {
                            const yearCounts = JSON.parse(yearCountsEl.textContent);
                            window.dispatchEvent(new CustomEvent('year-counts-update', { detail: yearCounts }));
                        } catch (e) {
                            console.error('Error parsing year counts:', e);
                        }
                    }

                    const genreCountsEl = document.getElementById('genre-counts-update');
                    if (genreCountsEl) {
                        try {
                            const genreCounts = JSON.parse(genreCountsEl.textContent);
                            window.dispatchEvent(new CustomEvent('genre-counts-update', { detail: genreCounts }));
                        } catch (e) {
                            console.error('Error parsing genre counts:', e);
                        }
                    }

                    const platformCountsEl = document.getElementById('platform-counts-update');
                    if (platformCountsEl) {
                        try {
                            const platformCounts = JSON.parse(platformCountsEl.textContent);
                            window.dispatchEvent(new CustomEvent('platform-counts-update', { detail: platformCounts }));
                        } catch (e) {
                            console.error('Error parsing platform counts:', e);
                        }
                    }

                    const rankDistEl = document.getElementById('rank-distribution-update');
                    if (rankDistEl) {
                        try {
                            const rankDist = JSON.parse(rankDistEl.textContent);
                            window.dispatchEvent(new CustomEvent('rank-distribution-update', { detail: rankDist }));
                        } catch (e) {
                            console.error('Error parsing rank distribution:', e);
                        }
                    }
                } else {
                    const contentEl = document.getElementById('content');
                    if (contentEl) {
                        contentEl.innerHTML = html;
                        if (typeof window.initRankDistributionCharts === 'function') {
                            window.initRankDistributionCharts();
                        } else {
                            window.dispatchEvent(new CustomEvent('rank-distribution-init'));
                        }
                    }
                }

                // Push the clean SEO page URL when this filter state has one
                // (single genre/platform/year/decade) so shared links point
                // at the indexable page
                const pushUrl = (typeof seoCleanUrl === 'function' &&
                    seoCleanUrl(params, this.minYear, this.maxYear)) || url;
                if (historyMethod) {
                    this._writeHistory(historyMethod, pushUrl, filterKey);
                }
                this._failedFilterKey = null;
                // The client render sets the tab with the heading; this path
                // has to as well, or the tab lags until the engine loads.
                if (window.documentTitleSuffix) {
                    document.title = this._documentTitle(this._buildDynamicTitle());
                }
            } catch (err) {
                if (err.name !== 'AbortError') {
                    console.error('Error fetching results:', err);
                    // The list is as it was, and the controls ahead of it
                    this._failedFilterKey = filterKey;
                    this._rollBackIfStranded();
                }
            } finally {
                // An aborted render finishes after what replaced it
                if (!signal.aborted) {
                    this.isLoading = false;
                    clearLoading('game-results-container');
                }
                if (this.filters.highlight) {
                    delete this.filters.highlight;
                }
            }
        },

        performClientUpdate(options = {}) {
            // historyMethod: null re-renders without touching the URL. A
            // server page or jump this overtakes is answered or dropped when
            // it lands (utils-loadmore.js, engineForSameList).
            const { historyMethod = 'pushState' } = options;

            this.isLoading = true;

            const highlightId = this.filters.highlight ? parseInt(this.filters.highlight) : null;

            const gameListContainer = document.getElementById('game-list-container');
            const countContainer = document.querySelector('.result-count');
            const loadMoreContainer = document.querySelector('.load-more-container');

            if (!gameListContainer) {
                console.error('[CSF] game-list-container not found');
                this.updateFacetCounts();
                this.isLoading = false;
                return;
            }

            const result = this._csf.applyFilters(this.filters);
            if (!result) {
                this.isLoading = false;
                return;
            }

            const state = this._csf.renderResults(result, gameListContainer, {
                highlightId,
                showRank: this.hasActiveFilters() ? 'filtered' : 'alltime'
            });
            // The list now shows the filters: nothing is left to roll back
            this._failedFilterKey = null;

            // Also empties Load Previous: a new result set starts at the top
            this._csf.renderWindowChrome();

            if (loadMoreContainer) {
                loadMoreContainer.innerHTML = this._csf.renderer.getLoadMoreHtml(state);
                this._initClientLoadMore(loadMoreContainer, gameListContainer, countContainer);
            }

            const dynamicTitle = this._buildDynamicTitle();
            const searchTitle = document.getElementById('search-title');
            if (searchTitle) {
                searchTitle.textContent = dynamicTitle;
            }
            const mobileTitle = document.getElementById('search-title-mobile');
            if (mobileTitle) {
                mobileTitle.textContent = dynamicTitle;
            }
            // The server composes the document title from this same heading,
            // so it has to follow the heading here as well - otherwise the
            // tab, a bookmark and a shared link all keep whatever the filter
            // state was at page load.
            if (window.documentTitleSuffix) {
                document.title = this._documentTitle(dynamicTitle);
            }

            if (state.facets) {
                const yearCountsArray = [];
                const yearFacets = state.facets.years || {};
                for (let y = this.minYear; y <= this.maxYear; y++) {
                    yearCountsArray.push({ year: y, count: yearFacets[y] || 0 });
                }
                window.dispatchEvent(new CustomEvent('year-counts-update', { detail: yearCountsArray }));

                window.dispatchEvent(new CustomEvent('genre-counts-update', { detail: state.facets.genres }));
                window.dispatchEvent(new CustomEvent('platform-counts-update', { detail: state.facets.platforms }));

                if (state.facets.platformGroups) {
                    this.platformGroupCounts = state.facets.platformGroups;
                    window.dispatchEvent(new CustomEvent('platform-group-counts-update', { detail: state.facets.platformGroups }));
                }

                if (state.facets.series) {
                    window.dispatchEvent(new CustomEvent('series-counts-update', { detail: state.facets.series }));
                }

                if (state.facets.rankDistribution) {
                    window.dispatchEvent(new CustomEvent('rank-distribution-update', { detail: state.facets.rankDistribution }));
                }
            }

            if (historyMethod) {
                this._writeHistory(historyMethod, this._filterUrl());
            }

            this.isLoading = false;

            if (this.filters.highlight) {
                delete this.filters.highlight;
            }
        },

        updateFacetCounts() {
            const result = this._csf.applyFilters(this.filters);
            if (!result || !result.facets) return;

            const yearCountsArray = [];
            const yearFacets = result.facets.years || {};
            for (let y = this.minYear; y <= this.maxYear; y++) {
                yearCountsArray.push({ year: y, count: yearFacets[y] || 0 });
            }
            window.dispatchEvent(new CustomEvent('year-counts-update', { detail: yearCountsArray }));

            window.dispatchEvent(new CustomEvent('genre-counts-update', { detail: result.facets.genres || {} }));
            window.dispatchEvent(new CustomEvent('platform-counts-update', { detail: result.facets.platforms || {} }));

            if (result.facets.platformGroups) {
                this.platformGroupCounts = result.facets.platformGroups;
                window.dispatchEvent(new CustomEvent('platform-group-counts-update', { detail: result.facets.platformGroups }));
            }

            if (result.facets.series) {
                window.dispatchEvent(new CustomEvent('series-counts-update', { detail: result.facets.series }));
            }

            if (result.facets.rankDistribution) {
                window.dispatchEvent(new CustomEvent('rank-distribution-update', { detail: result.facets.rankDistribution }));
            }
        },

        dispatchInitialCounts(options = {}) {
            const yearCountsEl = document.getElementById('year-counts-update');
            if (yearCountsEl) {
                try {
                    const yearCounts = JSON.parse(yearCountsEl.textContent);
                    window.dispatchEvent(new CustomEvent('year-counts-update', { detail: yearCounts }));
                } catch (e) {
                    console.error('Error parsing year counts:', e);
                }
            }

            const genreCountsEl = document.getElementById('genre-counts-update');
            if (genreCountsEl) {
                try {
                    const genreCounts = JSON.parse(genreCountsEl.textContent);
                    window.dispatchEvent(new CustomEvent('genre-counts-update', { detail: genreCounts }));
                } catch (e) {
                    console.error('Error parsing genre counts:', e);
                }
            }

            const platformCountsEl = document.getElementById('platform-counts-update');
            if (platformCountsEl) {
                try {
                    const platformCounts = JSON.parse(platformCountsEl.textContent);
                    window.dispatchEvent(new CustomEvent('platform-counts-update', { detail: platformCounts }));
                } catch (e) {
                    console.error('Error parsing platform counts:', e);
                }
            }

            const seriesCountsEl = document.getElementById('series-counts-update');
            if (seriesCountsEl) {
                try {
                    const seriesCounts = JSON.parse(seriesCountsEl.textContent);
                    window.dispatchEvent(new CustomEvent('series-counts-update', { detail: seriesCounts }));
                } catch (e) {
                    console.error('Error parsing series counts:', e);
                }
            }

            const hltbCountsEl = document.getElementById('hltb-counts-update');
            if (hltbCountsEl) {
                try {
                    const hltbCounts = JSON.parse(hltbCountsEl.textContent);
                    window.dispatchEvent(new CustomEvent('hltb-counts-update', { detail: hltbCounts }));
                } catch (e) {
                    console.error('Error parsing HLTB counts:', e);
                }
            }

            // Skip rank distribution on bfcache restore: the server-rendered data
            // reflects the initial page load state, not the current filters. The chart
            // preserves its bins via bfcache and gets fresh data from initClientFiltering().
            if (!options.skipRankDistribution) {
                const rankDistEl = document.getElementById('rank-distribution-update');
                if (rankDistEl) {
                    try {
                        const rankDist = JSON.parse(rankDistEl.textContent);
                        window.dispatchEvent(new CustomEvent('rank-distribution-update', { detail: rankDist }));
                    } catch (e) {
                        console.error('Error parsing rank distribution:', e);
                    }
                }
            }
        },

        _initClientLoadMore(loadMoreContainer, gameListContainer, countContainer) {
            const button = loadMoreContainer.querySelector('.load-more-button');
            if (!button) return;

            button.addEventListener('click', (event) => {
                // utils-loadmore.js also handles Load More, delegated from
                // #game-results-container; without this it loaded a second
                // page on every click of a client-rendered list.
                event.stopPropagation();
                button.classList.add('loading');
                button.disabled = true;

                const showRank = this.hasActiveFilters() ? 'filtered' : 'alltime';
                const state = this._csf.loadMore(gameListContainer, { showRank });

                this._csf.renderWindowChrome();
                loadMoreContainer.innerHTML = this._csf.renderer.getLoadMoreHtml(state);

                if (state.hasMore) {
                    this._initClientLoadMore(loadMoreContainer, gameListContainer, countContainer);
                }
            });
        },

        updateResults() {
            if (!this.initialized || !this._debouncedUpdate) return;
            this.requestClientFilteringInit('search');
            this._debouncedUpdate();
        },

        updateUrlAndResults() {
            if (!this.initialized) return;
            this.requestClientFilteringInit('navigation');
            if (this._debouncedUpdate) this._debouncedUpdate.cancel();
            this.performUpdate({ partial: false, historyMethod: 'pushState' });
        },

        debouncedFilterUpdate() {
            if (this._debouncedFilter) {
                this.requestClientFilteringInit('filter-change');
                this._debouncedFilter();
            }
        },

        updateUrl() {
            this.debouncedFilterUpdate();
        },

        updateSort(newSort) {
            this.filters.sort = newSort;
            if (this.initialized) {
                this.requestClientFilteringInit('sort-change');
                this.debouncedFilterUpdate();
            }
        },

        toggleSortDirection() {
            this.filters.sortDirection = this.filters.sortDirection === 'asc' ? 'desc' : 'asc';
            if (this.initialized) {
                this.requestClientFilteringInit('sort-direction');
                this.debouncedFilterUpdate();
            }
        },

        setViewMode(mode) {
            this.viewMode = mode;
            storePreference('gameViewMode', mode);
            if (this._csf) {
                this._csf.setViewMode(mode);
            }
            if (this.clientFilterReady && this._csf) {
                // A view is not a filter: re-render, leave the URL alone. It
                // used to replaceState with _filterUrl(), which on an
                // unfiltered page wrote /games/?start=..&end=.. over `/`.
                // A server page this overtakes is answered when it lands, the
                // list being the same (utils-loadmore.js, engineForSameList).
                this.performClientUpdate({ historyMethod: null });
            } else if (mode === 'grid') {
                // Until the bundle renders a grid, grid mode shows the server's
                // rows (styles.css hides them only once a .game-grid exists).
                this.requestClientFilteringInit('grid-view');
            }
        },

        // True when grid mode is on but the list still holds the server's
        // rows: the server renders no grid cards, so the bundle must.
        _needsClientGrid() {
            if (this.viewMode !== 'grid') return false;
            const container = document.getElementById('game-list-container');
            return !!container && !container.querySelector('.game-grid');
        }
    }));
});
