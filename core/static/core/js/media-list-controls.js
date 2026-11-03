/**
 * Filter state for a ranking page whose filters are a plain HTMX GET form.
 *
 * Two shared pieces of UI bind to an Alpine component rather than to a page:
 *
 *   core/includes/_media_list_controls.html  sort, direction, view, jump box
 *   core/includes/_year_grid.html            the year heatmap
 *   core/includes/_genre_filter.html         the genre tree
 *
 * They expect the enclosing component to expose `filters`, `genres`,
 * `initialized`, `debouncedFilterUpdate()`, `handleFilterChange()`,
 * `updateSort()`, `toggleSortDirection()`, `viewMode` and `setViewMode()`.
 * The games rankings page satisfies that with `filterComponent`, which also
 * owns platforms, series, playtime, saved filters and client-side filtering.
 * This is the small implementation for the album rankings page, which has a
 * real <form> doing the filtering.
 *
 * Every change ends the same way: the filter state is written into that
 * form's fields and a bubbling `change` event is dispatched. HTMX re-requests
 * the results from it, and once the client-side filtering bundle has taken
 * the form over it re-renders locally from the same fields instead. The form
 * stays the single source of truth, so the two paths cannot disagree.
 */

/** localStorage, treated as absent when a private window refuses it. */
function readStoredPreference(key) {
    if (!key) return null;
    try {
        return localStorage.getItem(key);
    } catch (e) {
        return null;
    }
}

function storePreference(key, value) {
    if (!key) return;
    try {
        localStorage.setItem(key, value);
    } catch (e) {
        // Quota or private mode: the preference just does not persist.
    }
}

/**
 * The CSRF token from the cookie (settings.CSRF_COOKIE_NAME).
 *
 * `BaseMediaListRenderer` has one of these too, but it is a method on a
 * class in the deferred filtering bundle, while this file has to load
 * before Alpine - so it is not reachable from here.
 */
function readCsrfToken() {
    const match = document.cookie.match(/(?:^|;\s*)am_csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : '';
}

/** Parse a JSON <script> block the page rendered, or return a fallback. */
function readJsonScript(id, fallback) {
    const el = id && document.getElementById(id);
    if (!el) return fallback;
    try {
        return JSON.parse(el.textContent);
    } catch (e) {
        return fallback;
    }
}

/** Join names with commas and an "and", as core/services/titles.py does. */
function joinNames(names) {
    if (!names.length) return '';
    if (names.length === 1) return names[0];
    if (names.length === 2) return names.join(' and ');
    return names.slice(0, -1).join(', ') + ', and ' + names[names.length - 1];
}

function mediaListControlsData(config) {
    const settings = config || {};
    const stored = readJsonScript(settings.filtersDataId || 'filters-data', null);
    // The tracking status filter's parameter name. A section without one
    // leaves the key present and empty, which every branch below reads as
    // "no status filter", so nothing has to special-case its absence.
    const statusKey = settings.statusKey || 'listened';

    return {
        minYear: settings.minYear || 0,
        maxYear: settings.maxYear || 0,
        genres: readJsonScript(settings.genresDataId || 'genres-data', []),
        filters: Object.assign(
            {
                q: '',
                start: settings.minYear || null,
                end: settings.maxYear || null,
                genres: [],
                // A user-tracking status filter, as an array of the values
                // the server accepts. Named for its parameter, which is the
                // section's: `listened` on the album rankings.
                [statusKey]: [],
                sort: settings.sort || 'rank',
                sortDirection: settings.dir || 'asc'
            },
            stored || {}
        ),

        viewMode: readStoredPreference(settings.viewModeKey) || 'list',
        yearExpanded: readStoredPreference('yearExpanded') !== 'false',
        genresExpanded: readStoredPreference('genresExpanded') !== 'false',

        // The year grid asks before requesting an update, so that building
        // the grid on load does not immediately re-filter the page.
        initialized: false,
        defaultSort: settings.defaultSort || 'rank',
        _popstateListener: null,
        _genresSelectedListener: null,

        // -- saved filters ---------------------------------------------------
        // Inert unless the page passed a `savedFiltersUrl`: the shared
        // partials render nothing without one, so a section that has not
        // opted in carries this state and never shows it.
        savedFiltersUrl: settings.savedFiltersUrl || '',
        maxSavedFilters: settings.maxSavedFilters || 10,
        savedFiltersOpen: false,
        savedFiltersLoading: false,
        savedFiltersLoaded: false,
        savedFilters: [],
        // Read by the shared year grid, which has always passed
        // `isApplyingSavedFilter` behind a `typeof` guard. Defining it here
        // is what makes the grid stop previewing a range mid-apply.
        applyingSavedFilter: false,
        saveFilterModalOpen: false,
        saveFilterName: '',
        saveFilterError: '',
        saveFilterSaving: false,
        renameFilterModalOpen: false,
        renameFilterName: '',
        renameFilterError: '',
        renameFilterSaving: false,
        renameFilterTarget: null,
        deleteFilterModalOpen: false,
        deleteFilterTarget: null,
        deleteFilterDeleting: false,
        _savedFilterResetHandler: null,

        init() {
            this._applyViewMode();
            this._popstateListener = () => this._syncFromUrl();
            window.addEventListener('popstate', this._popstateListener);

            // Filter components created late (the mobile sheet on first
            // open, a sidebar skipped on a narrow first load) missed the
            // counts announced so far; this is their request for them.
            this._facetRefreshListener = () => this.refreshFacetCounts();
            window.addEventListener('mobile-filter-opened', this._facetRefreshListener);

            // Leading edge, as on the games page: a click applies at once
            // rather than after the wait, and a burst still collapses into
            // one trailing commit, which is skipped if it would apply the
            // same filters again and otherwise replaces the history entry
            // the leading one pushed. Only once the client engine can
            // answer: before that each commit is a server request, and the
            // old trailing wait is what lets the engine load first.
            this._leadingCommit = debounceLeading(burst => {
                this.commit({ historyReplace: burst.followsLeading });
            }, 250, {
                canLead: () => this._clientEngineReady(),
                keyOf: () => JSON.stringify(this.filters),
                // Let the click's own feedback paint before the re-render.
                schedule: afterNextPaint
            });

            // A genre clicked in a row filters the list without going
            // through this component - the row's handler writes the form
            // and re-renders directly, which the engine reads. This
            // component still owns `filters`, which the heading and the
            // sidebar's genre tree are both built from, so without being
            // told it kept showing the previous selection: the list
            // filtered, the heading did not, and a refresh "fixed" it
            // because the server then rendered the heading from the URL.
            this._genresSelectedListener = event => {
                const ids = (event.detail && event.detail.genres) || [];
                this.filters.genres = ids.map(String);
                this._applyTitle();
            };
            window.addEventListener(
                'genres-selected', this._genresSelectedListener
            );

            // The year grid and the genre tree read their counts from
            // events, not from the page, so the counts the server just
            // rendered have to be announced - the tree shows a skeleton
            // until the first genre-counts-update arrives.
            this._swapListener = event => {
                if (!settings.resultsContainerId) return;
                if (event.target && event.target.id === settings.resultsContainerId) {
                    this.publishFacetCounts();
                }
            };
            document.body.addEventListener('htmx:afterSwap', this._swapListener);

            // A filter request that fails (a 429, a 500, the network) leaves
            // the sidebar and the heading on the filters it asked for, while
            // the list stays on the ones it was rendered with. An engine still
            // loading renders the form as it takes over; with none to come,
            // the controls go back to what the list shows.
            this._failedRequestListener = event => {
                const form = this._form();
                const detail = event.detail || {};
                if (!form || detail.elt !== form || detail.successful) return;
                const engine = this._clientEngine();
                if (engine && !engine.failed) return;
                this._answerFailedRequest(detail.requestConfig && detail.requestConfig.parameters);
            };
            this._engineFailedListener = event => {
                this._answerFailedRequest(event.detail && event.detail.parameters);
            };
            if (settings.renderedFiltersId) {
                document.body.addEventListener('htmx:afterRequest', this._failedRequestListener);
                window.addEventListener('client-engine-failed', this._engineFailedListener);
            }
            // Let the subcomponents build themselves from the state the
            // server rendered before any of them can ask for a refilter -
            // and before the first counts go out, since Alpine initialises
            // this component before the children that listen for them.
            this.$nextTick(() => {
                this.publishFacetCounts();
                this.initialized = true;
            });
        },

        destroy() {
            if (this._popstateListener) {
                window.removeEventListener('popstate', this._popstateListener);
                this._popstateListener = null;
            }
            if (this._genresSelectedListener) {
                window.removeEventListener(
                    'genres-selected', this._genresSelectedListener
                );
                this._genresSelectedListener = null;
            }
            if (this._swapListener) {
                document.body.removeEventListener('htmx:afterSwap', this._swapListener);
                this._swapListener = null;
            }
            if (this._facetRefreshListener) {
                window.removeEventListener('mobile-filter-opened', this._facetRefreshListener);
                this._facetRefreshListener = null;
            }
            if (this._failedRequestListener) {
                document.body.removeEventListener('htmx:afterRequest', this._failedRequestListener);
                window.removeEventListener('client-engine-failed', this._engineFailedListener);
                this._failedRequestListener = null;
            }
            if (this._leadingCommit) this._leadingCommit.cancel();
            if (this._savedFilterResetHandler) {
                document.removeEventListener(
                    'htmx:afterSwap', this._savedFilterResetHandler
                );
                this._savedFilterResetHandler = null;
            }
        },

        /**
         * Re-broadcast the facet counts the server rendered into the page.
         *
         * A client-side filtering bundle dispatches the same two events from
         * its own data, so the subcomponents never need to know which side
         * counted.
         */
        publishFacetCounts() {
            const publish = (elementId, eventName) => {
                const el = document.getElementById(elementId);
                if (!el) return;
                try {
                    window.dispatchEvent(
                        new CustomEvent(eventName, { detail: JSON.parse(el.textContent) })
                    );
                } catch (e) {
                    // A malformed block should not take the sidebar down.
                }
            };
            publish('year-counts-update', 'year-counts-update');
            publish('genre-counts-update', 'genre-counts-update');
            publish('rank-distribution-update', 'rank-distribution-update');
        },

        // -- sort and view ---------------------------------------------------

        updateSort(newSort) {
            if (newSort === this.filters.sort) return;
            this.filters.sort = newSort;
            this.commit();
        },

        toggleSortDirection() {
            this.filters.sortDirection =
                this.filters.sortDirection === 'asc' ? 'desc' : 'asc';
            this.commit();
        },

        setViewMode(mode) {
            if (mode === this.viewMode) return;
            this.viewMode = mode;
            storePreference(settings.viewModeKey, mode);
            this._applyViewMode();
            // A client-side renderer re-renders in the new mode; the
            // server-rendered page needs nothing, since it renders both and
            // the container class decides which one shows.
            window.dispatchEvent(
                new CustomEvent('media-view-mode', { detail: { mode } })
            );
        },

        // -- filters ---------------------------------------------------------

        /** What the year grid and genre tree call after a change. */
        debouncedFilterUpdate() {
            this._leadingCommit();
        },

        /**
         * The page's client-side filtering engine, which a page names with
         * `clientEngine`; null when it names none.
         * @private
         */
        _clientEngine() {
            return typeof settings.clientEngine === 'function'
                ? settings.clientEngine()
                : null;
        },

        /**
         * Whether that engine can take the page over. Always false without
         * one, so the component behaves as a plain HTMX form.
         * @private
         */
        _clientEngineReady() {
            const engine = this._clientEngine();
            return Boolean(engine && engine.isReady && engine.isReady());
        },

        /**
         * Re-send the year and genre counts to components that missed them.
         *
         * The engine counts the current state when it can; before it is
         * ready the server-rendered counts in the page are the current ones.
         */
        refreshFacetCounts() {
            const engine = this._clientEngine();
            if (engine && engine.republishFacets && engine.republishFacets()) return;
            this.publishFacetCounts();
        },

        /**
         * What a subcomponent's `filter-changed` event carries.
         *
         * The tree dispatches the selected genres as objects; the filter
         * state and the form both want their ids.
         */
        handleFilterChange(type, items) {
            if (!type || !Array.isArray(items)) return;
            this.filters[type] = items.map(item =>
                item && typeof item === 'object' && item.id !== undefined
                    ? String(item.id)
                    : String(item)
            );
            this.debouncedFilterUpdate();
        },

        /**
         * Add or remove one value of a multi-select status filter.
         *
         * The shared status control drives whichever parameter a section
         * uses through this; games' filterComponent has the same pair.
         */
        toggleStatusValue(key, value) {
            const current = this.filters[key] || [];
            const index = current.indexOf(value);
            if (index === -1) {
                current.push(value);
            } else {
                current.splice(index, 1);
            }
            this.filters[key] = current;
            this.debouncedFilterUpdate();
        },

        resetStatus(key) {
            this.filters[key] = [];
            this.debouncedFilterUpdate();
        },

        resetYears() {
            this.filters.start = this.minYear;
            this.filters.end = this.maxYear;
            this.debouncedFilterUpdate();
        },

        resetGenres() {
            this.filters.genres = [];
            window.dispatchEvent(new CustomEvent('genres-reset'));
            this.debouncedFilterUpdate();
        },

        resetAllFilters() {
            this.filters.q = '';
            this.filters.genres = [];
            this.filters[statusKey] = [];
            this.filters.start = this.minYear;
            this.filters.end = this.maxYear;
            this.filters.sort = this.defaultSort;
            this.filters.sortDirection = 'asc';
            const form = this._form();
            if (form) {
                const artists = form.querySelector('[name="artists"]');
                if (artists) artists.value = '';
            }
            window.dispatchEvent(new CustomEvent('genres-reset'));
            this.commit();
        },

        hasActiveFilters() {
            const form = this._form();
            const artist = form && form.querySelector('[name="artists"]');
            return Boolean(
                this.filters.q ||
                this.filters.genres.length ||
                (this.filters[statusKey] || []).length ||
                (artist && artist.value) ||
                this.hasYearFilter()
            );
        },

        hasYearFilter() {
            return !isWholeYearRange(
                this.filters.start, this.filters.end, this.minYear, this.maxYear
            );
        },

        // -- saved filters ---------------------------------------------------
        //
        // A filter combination worth returning to is stored as the JSON this
        // component already keeps, so applying one is a local assignment plus
        // the ordinary `commit()`. There is no apply endpoint and no reload:
        // `commit()` writes the form and fires the bubbling `change` that
        // drives either HTMX or the client-side filtering bundle, whichever
        // is live.

        /**
         * Open the dropdown, fetching the list the first time only.
         *
         * The dropdown opens straight away rather than after the request, so
         * it never feels like the button missed the click.
         */
        async loadSavedFilters() {
            if (this.savedFiltersLoading) return;
            this.savedFiltersOpen = true;
            if (this.savedFiltersLoaded) return;

            this.savedFiltersLoading = true;
            try {
                const response = await fetch(this.savedFiltersUrl);
                if (response.ok) {
                    const data = await response.json();
                    this.savedFilters = data.filter_sets || [];
                    this.savedFiltersLoaded = true;
                }
            } catch (e) {
                // Offline or blocked: the dropdown stays empty rather than
                // leaving a spinner running forever.
            } finally {
                this.savedFiltersLoading = false;
            }
        },

        /**
         * Apply a stored combination to the live filter state.
         *
         * `applyingSavedFilter` is held for the duration because the year
         * grid treats a range it is mid-way through building as a preview;
         * it is cleared on the swap that the commit causes, with a timer as
         * the fallback for the case where nothing swaps because the engine
         * answered locally.
         */
        applySavedFilter(filter) {
            const saved = (filter && filter.filters) || {};
            this.applyingSavedFilter = true;

            this.filters.q = saved.q || '';
            this.filters.start = saved.start || this.minYear;
            this.filters.end = saved.end || this.maxYear;
            // Both through `_asList`: the stored blob is accepted
            // unvalidated, so a hand-written or hand-edited one can hold
            // the comma-joined spelling the URL uses, and a bare string
            // has no `.map` to call.
            this.filters.genres = this._asList(saved.genres).map(String);
            this.filters[statusKey] = this._asList(saved[statusKey]);
            this.filters.sort = saved.sort || this.defaultSort;
            // Games saved this and never restored it, so a saved filter
            // silently lost its direction. Both halves round-trip here.
            this.filters.sortDirection = saved.sortDirection || 'asc';
            // A saved combination has no artist, so a `?artists=` the page
            // was opened with must not narrow it - as Clear All drops it.
            const form = this._form();
            const artists = form && form.querySelector('[name="artists"]');
            if (artists) artists.value = '';

            this.savedFiltersOpen = false;
            // Deliberately *not* announcing `genres-reset` here. The mobile
            // sheet answers it by clearing `filters.genres` outright (see
            // core/includes/_mobile_filter_genres.html), and the sheet shares
            // this component's state at every width, so telling the sidebar to
            // refresh wiped the very state just restored. The tree derives its
            // selected state from `filters` reactively, so it follows untold.
            this.commit();
            this._clearApplyingFlagSoon();
        },

        /** Open the save modal, named after the heading it would produce. */
        saveCurrentFilters() {
            this.saveFilterName = this.buildTitle();
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
            const invalid = this._nameProblem(name);
            if (invalid) {
                this.saveFilterError = invalid;
                return;
            }

            this.saveFilterSaving = true;
            this.saveFilterError = '';
            try {
                const response = await this._send(this.savedFiltersUrl, 'POST', {
                    name: name,
                    filters: this.savedFilterPayload()
                });
                if (response.ok) {
                    this.savedFilters.unshift(await response.json());
                    this.saveFilterModalOpen = false;
                } else {
                    this.saveFilterError = await this._errorMessage(
                        response, 'Failed to save filter'
                    );
                }
            } catch (e) {
                this.saveFilterError = 'Network error - please try again';
            } finally {
                this.saveFilterSaving = false;
            }
        },

        /**
         * The filter state as it is stored.
         *
         * Only the dimensions this component owns. The status key is named
         * for the section's parameter, so the stored shape matches what the
         * server would have put in the URL.
         */
        savedFilterPayload() {
            return {
                q: this.filters.q,
                start: this.filters.start,
                end: this.filters.end,
                genres: this.filters.genres,
                [statusKey]: this.filters[statusKey] || [],
                sort: this.filters.sort,
                sortDirection: this.filters.sortDirection
            };
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
            const invalid = this._nameProblem(name);
            if (invalid) {
                this.renameFilterError = invalid;
                return;
            }
            // Renaming to the name it already has is not worth a request,
            // and the server would reject it as a duplicate of itself.
            if (name === this.renameFilterTarget.name) {
                this.renameFilterModalOpen = false;
                return;
            }

            this.renameFilterSaving = true;
            this.renameFilterError = '';
            try {
                const response = await this._send(
                    this._savedFilterUrl(this.renameFilterTarget.id),
                    'PATCH',
                    { name: name }
                );
                if (response.ok) {
                    // Alpine proxies the array's entries, so writing the
                    // name here is what re-renders the dropdown row.
                    this.renameFilterTarget.name = name;
                    this.renameFilterModalOpen = false;
                } else {
                    this.renameFilterError = await this._errorMessage(
                        response, 'Failed to rename filter'
                    );
                }
            } catch (e) {
                this.renameFilterError = 'Network error - please try again';
            } finally {
                this.renameFilterSaving = false;
            }
        },

        deleteSavedFilter(filter) {
            this.deleteFilterTarget = filter;
            this.deleteFilterDeleting = false;
            this.deleteFilterModalOpen = true;
            this.savedFiltersOpen = false;
        },

        async confirmDeleteFilter() {
            this.deleteFilterDeleting = true;
            try {
                const response = await this._send(
                    this._savedFilterUrl(this.deleteFilterTarget.id), 'DELETE'
                );
                if (response.ok) {
                    const index = this.savedFilters.indexOf(this.deleteFilterTarget);
                    if (index > -1) this.savedFilters.splice(index, 1);
                    this.deleteFilterModalOpen = false;
                }
            } catch (e) {
                // Leave the modal open so the reader can try again.
            } finally {
                this.deleteFilterDeleting = false;
            }
        },

        // -- plumbing --------------------------------------------------------

        /**
         * A stored multi-value filter in the array form `filters` holds.
         *
         * The `filters` blob is stored unvalidated, so a row can carry the
         * comma-joined spelling the URL uses rather than an array, and a
         * bare string would have no `.map`.
         * @private
         */
        _asList(value) {
            if (Array.isArray(value)) return value;
            if (typeof value === 'string') {
                return value.split(',').filter(Boolean);
            }
            return [];
        },

        /** @private */
        _savedFilterUrl(id) {
            return this.savedFiltersUrl + id + '/';
        },

        /** The name rules the server enforces, checked before asking. @private */
        _nameProblem(name) {
            if (!name) return 'Filter name is required';
            if (name.length > 255) {
                return 'Filter name must be 255 characters or less';
            }
            return null;
        },

        /** @private */
        _send(url, method, body) {
            const options = {
                method: method,
                headers: { 'X-CSRFToken': readCsrfToken() }
            };
            if (body !== undefined) {
                options.headers['Content-Type'] = 'application/json';
                options.body = JSON.stringify(body);
            }
            return fetch(url, options);
        },

        /** The server's own message where it sent one. @private */
        async _errorMessage(response, fallback) {
            try {
                const payload = await response.json();
                return payload.error || fallback;
            } catch (e) {
                return 'Error ' + response.status + ': ' + response.statusText;
            }
        },

        /** @private */
        _clearApplyingFlagSoon() {
            const clear = () => {
                this.applyingSavedFilter = false;
                if (this._savedFilterResetHandler) {
                    document.removeEventListener(
                        'htmx:afterSwap', this._savedFilterResetHandler
                    );
                    this._savedFilterResetHandler = null;
                }
            };
            this._savedFilterResetHandler = clear;
            document.addEventListener('htmx:afterSwap', clear, { once: true });
            // Nothing swaps when the browser answered the filter locally,
            // so the flag needs a deadline of its own.
            setTimeout(clear, 500);
        },

        /** @private */
        _form() {
            return document.getElementById(settings.formId);
        },

        /**
         * Toggle the list container's view-list / view-grid class, which is
         * what the shared grid CSS keys off.
         * @private
         */
        _applyViewMode() {
            const container = document.getElementById(settings.listContainerId);
            if (!container) return;
            container.classList.toggle('view-grid', this.viewMode === 'grid');
            container.classList.toggle('view-list', this.viewMode !== 'grid');
        },

        /**
         * The current filter state as a query string, for the CSV link.
         */
        downloadQuery() {
            const params = new URLSearchParams();
            if (this.filters.q) params.set('q', this.filters.q);
            if (this.hasYearFilter()) {
                params.set('start', this.filters.start);
                params.set('end', this.filters.end);
            }
            if (this.filters.genres.length) {
                params.set('genres', this.filters.genres.join(','));
            }
            if ((this.filters[statusKey] || []).length) {
                params.set(statusKey, this.filters[statusKey].join(','));
            }
            if (this.filters.sort && this.filters.sort !== this.defaultSort) {
                params.set('sort', this.filters.sort);
            }
            if (this.filters.sortDirection !== 'asc') {
                params.set('dir', this.filters.sortDirection);
            }
            return params.toString();
        },

        /**
         * The filter state's labels, which the heading and the tab title share.
         *
         * Mirrors `music.views._title_parts`. The heading sits outside the
         * swapped results container, so neither path gets it for free: the
         * server sends it back out of band, and this sets it directly when
         * filtering happens in the browser.
         * @private
         */
        _titleParts() {
            const names = this.filters.genres
                .map(id => {
                    const genre = this.genres.find(
                        entry => String(entry.id) === String(id)
                    );
                    return genre ? genre.name : null;
                })
                .filter(Boolean);

            // Mirrors the status labels `_title_parts` names. Without them
            // the title would change the moment filtering moved from the
            // server to the browser.
            const statuses = this.filters[statusKey] || [];
            const labels = (settings.statusOptions || [])
                .filter(option => statuses.includes(option.value))
                .map(option => option.title);

            // No control picks artists, so their names come with the field
            // the page rendered them into (`_title_parts`'s artists).
            const form = this._form();
            const field = form && form.querySelector('[name="artists"]');
            const artists = field && field.value && field.dataset.label
                ? field.dataset.label
                : '';

            return {
                query: this.filters.q || '',
                genres: joinNames(names),
                artists,
                statuses: joinNames(labels)
            };
        },

        /**
         * The heading, composed from the filter state.
         *
         * Mirrors `music.views._filter_title`, as games' `_buildDynamicTitle`
         * mirrors its own server-side builder.
         */
        buildTitle(parts = this._titleParts()) {
            if (parts.query) {
                return `${settings.titleSearchNoun || 'Items'} matching \u201c` +
                    `${parts.query}\u201d`;
            }

            const genreLabel = parts.genres ? ' ' + parts.genres : '';
            const window_ = buildTimeWindow(
                this.filters.start,
                this.filters.end,
                this.minYear,
                this.maxYear
            );
            const timeSuffix = window_ ? ' of ' + window_ : '';
            const statusSuffix = parts.statuses ? ': ' + parts.statuses : '';
            const artistLabel = parts.artists ? ' by ' + parts.artists : '';

            const noun = settings.titleNoun || 'Items';
            return `Most Acclaimed${genreLabel} ${noun}${artistLabel}` +
                `${timeSuffix}${statusSuffix}`;
        },

        /**
         * A filtered page's tab title without its suffix, or '' when nothing
         * filters. Mirrors `music.views._tab_title`.
         */
        buildTabTitle(parts = this._titleParts()) {
            return shortTitle([
                parts.query ? `\u201c${parts.query}\u201d` : '',
                parts.genres,
                parts.artists,
                shortTimeWindow(
                    this.filters.start,
                    this.filters.end,
                    this.minYear,
                    this.maxYear
                ),
                parts.statuses
            ]);
        },

        /**
         * The heading, and the tab title a reload of the address would give.
         *
         * A filter change always lands on the rankings path (`/?...`), where
         * a filtered page's tab lists its facets. Only Back can reach a
         * landing page's own path, which keeps the heading it is indexed by.
         * Nothing is kept from the page's load: a title remembered for "the
         * state the page was served for" came back for any state with the
         * same facets, the landing page's heading included on /?genres=...
         * @private
         */
        _applyTitle({ onLandingPath = false } = {}) {
            const parts = this._titleParts();
            const title = this.buildTitle(parts);
            ['search-title-text', 'search-title-mobile-text'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.textContent = title;
            });
            if (!window.documentTitleSuffix) return;
            const tabTitle = onLandingPath ? '' : this.buildTabTitle(parts);
            document.title = tabTitle
                ? tabTitle + (window.tabTitleSuffix || '')
                : title + window.documentTitleSuffix;
        },

        /**
         * Write the filter state onto the form (_fieldValues) and announce it.
         */
        commit({ historyReplace = false } = {}) {
            const form = this._form();
            if (!form) return;

            Object.entries(this._fieldValues()).forEach(([name, value]) => {
                const field = form.querySelector(`[name="${name}"]`);
                if (field) field.value = value;
            });

            this._applyTitle();
            // `historyReplace` asks a client engine to replace rather than
            // push the history entry: a burst's trailing commit belongs to
            // the change its leading one already recorded. HTMX ignores it.
            form.dispatchEvent(new CustomEvent('change', {
                bubbles: true,
                detail: { historyReplace }
            }));
        },

        /**
         * A failed filter request with nobody else to answer it: the
         * controls go back to the list, unless the reader has moved on.
         * @private
         */
        _answerFailedRequest(sent) {
            if (!this._movedOnFrom(sent)) this.rollBackToTheList();
        },

        /**
         * Whether the reader has changed anything since a request sent
         * `sent` (htmx's parameters). A newer change answers for itself:
         * one still in a debounce, which only `filters` holds yet, and one
         * queued behind the request or on its way, which htmx sends from
         * the form as it stands then. Rolling back under either lost the
         * newer click, or sent the old filters in its place.
         *
         * What was sent is read back into the controls' own terms, as the
         * URL is on Back (`_filtersFrom`), and compared with what they hold
         * now: a form the server rendered can spell a filter otherwise
         * (`?start=1990` sends no end; `filters` has one), and a request
         * goes out from paths that are not a commit (Enter, a row's genre),
         * so no record of what a commit wrote can stand in for it.
         * @private
         */
        _movedOnFrom(sent) {
            const form = this._form();
            if (!form || !sent) return false;
            const asSent = Object.assign({ genres: this.filters.genres },
                this._filtersFrom(name => {
                    const value = htmxParameter(sent, name);
                    return value === undefined ? null : value;
                }));
            if (JSON.stringify(this._fieldValues()) !==
                    JSON.stringify(this._fieldValues(asSent))) {
                return true;
            }
            return [...form.elements].some(field => {
                // An unnamed control sends nothing, so it cannot differ
                if (!field.name) return false;
                const value = htmxParameter(sent, field.name);
                return value !== undefined && value !== field.value;
            });
        },

        /**
         * What commit() writes into the form for `filters`. A year range
         * covering everything is written as empty, which is how the server
         * spells "no year filter"; the grid spells it as the full range.
         * @private
         */
        _fieldValues(filters = this.filters) {
            const hasYears = !isWholeYearRange(
                filters.start, filters.end, this.minYear, this.maxYear
            );
            return {
                q: filters.q || '',
                start: hasYears ? filters.start : '',
                end: hasYears ? filters.end : '',
                genres: filters.genres.join(','),
                [statusKey]: (filters[statusKey] || []).join(','),
                sort: filters.sort,
                dir: filters.sortDirection,
            };
        },

        /**
         * Put the form, the controls and the heading back on the filters the
         * list was rendered with: `settings.renderedFiltersId`, the server's
         * echo of its request, spelled as the form's fields are.
         */
        rollBackToTheList() {
            const form = this._form();
            const echo = settings.renderedFiltersId &&
                document.getElementById(settings.renderedFiltersId);
            if (!form || !echo) return;
            if (this._leadingCommit) this._leadingCommit.cancel();
            // A page with no genre tree echoes no genres
            const rendered = name => (echo.hasAttribute('data-' + name)
                ? echo.getAttribute('data-' + name) || ''
                : null);
            ['q', 'start', 'end', 'artists', 'genres', statusKey, 'sort', 'dir']
                .forEach(name => {
                    const field = form.querySelector(`[name="${name}"]`);
                    if (field && rendered(name) !== null) field.value = rendered(name);
                });
            this._takeFilters(rendered);
        },

        /**
         * Set `filters` from a source of the form's parameters - the URL, or
         * the list's echo - and rebuild the heading. A name the source does
         * not give reads as empty, its default, except genres, which a
         * source with no genre tree gives as null and which then keep their
         * value.
         * @private
         */
        _takeFilters(get) {
            Object.assign(this.filters, this._filtersFrom(get));
            // On a landing page's path the path itself is the filter
            this._applyTitle({
                onLandingPath: Boolean(settings.landingPath) &&
                    window.location.pathname === settings.landingPath
            });
        },

        /**
         * The filters a source of the form's parameters names, by the rules
         * `_takeFilters` sets them with. Genres a source does not give keep
         * their value; anything else reads as empty, its default.
         * @private
         */
        _filtersFrom(get) {
            const text = name => get(name) || '';
            const number = (name, fallback) => {
                const parsed = parseInt(get(name), 10);
                return Number.isFinite(parsed) ? parsed : fallback;
            };
            const list = name => text(name).split(',').filter(Boolean);
            return {
                q: text('q'),
                start: number('start', this.minYear),
                end: number('end', this.maxYear),
                // Left out, not copied, so the reactive array is not replaced
                ...(get('genres') !== null ? { genres: list('genres') } : {}),
                [statusKey]: list(statusKey),
                sort: text('sort') || this.defaultSort,
                sortDirection: text('dir') || 'asc',
            };
        },

        /**
         * Re-read the filter state from the URL after a Back/Forward.
         * @private
         */
        _syncFromUrl() {
            // Nothing queued before Back may apply after it.
            if (this._leadingCommit) this._leadingCommit.cancel();
            const params = landingFilterParams(
                settings.landingPath, settings.landingSearch
            );
            // The heading names the artist from the form's field, so it is
            // restored here, before the heading is rebuilt, and not left to
            // the engine's popstate listener, which may run after this one
            const form = this._form();
            const artists = form && form.querySelector('[name="artists"]');
            if (artists) artists.value = params.get('artists') || '';
            // Every name, so that one the URL leaves out is cleared
            this._takeFilters(name => params.get(name) || '');
        }
    };
}

/**
 * Sort state for an entity list - artists, source lists, developers.
 *
 * These pages have no filter sidebar: a search box, a sort and sometimes one
 * select. `core/includes/_entity_sort_controls.html` binds to this, so the
 * dropdown-and-direction-toggle the games developer list has is what every
 * such page shows, instead of a pair of native selects on some of them.
 *
 * Config: url, target (the HTMX swap target), sort, dir, defaultSort,
 * ascendingSorts, and extraFields - the names of other inputs whose values
 * have to ride along with the request.
 */
function entityListControlsData(config) {
    const settings = config || {};
    const defaultSort = settings.defaultSort || settings.sort || '';
    // Each sort has a direction that is obviously right first time: a name
    // reads A-Z, a count or a year reads biggest first. It is also the one
    // the server takes when the URL names none, so the URL leaves it out
    // per sort: one default for every sort put Z-A names back to A-Z on a
    // reload. Each view's ASCENDING_SORTS agrees (music/views.py,
    // games/views/lists.py).
    const ascending = settings.ascendingSorts || ['name', 'alpha', 'order', 'rank'];
    const directionFor = sort => (ascending.indexOf(sort) === -1 ? 'desc' : 'asc');

    return {
        sort: settings.sort || defaultSort,
        sortDirection: settings.dir || directionFor(settings.sort || defaultSort),

        updateSort(newSort) {
            if (newSort === this.sort) return;
            this.sort = newSort;
            this.sortDirection = directionFor(newSort);
            this._request();
        },

        toggleSortDirection() {
            this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
            this._request();
        },

        /** @private */
        _request() {
            const url = new URL(window.location);
            const setParam = (name, value, fallback) => {
                if (value && value !== fallback) {
                    url.searchParams.set(name, value);
                } else {
                    url.searchParams.delete(name);
                }
            };
            setParam('sort', this.sort, defaultSort);
            setParam('dir', this.sortDirection, directionFor(this.sort));
            url.searchParams.delete('page');

            const values = { sort: this.sort, dir: this.sortDirection };
            (settings.extraFields || []).forEach(name => {
                const field = document.querySelector(`[name="${name}"]`);
                if (field) values[name] = field.value;
            });

            if (typeof htmx !== 'undefined') {
                // htmx pushes the request's own address, HTMXPushURLMiddleware
                // having asked it to, in an entry Back reloads. This tidies
                // that entry rather than pushing a second one beside it,
                // which took two presses of Back to leave and was not
                // reloaded on the way.
                const left = window.location.href;
                htmx.ajax('GET', settings.url, {
                    target: settings.target,
                    swap: 'innerHTML',
                    values
                }).then(() => {
                    if (window.location.href !== left) window.history.replaceState(window.history.state, '', url);
                }, () => {
                    // Failed or aborted: htmx pushed nothing, and has said so
                });
            }
        }
    };
}

if (typeof document !== 'undefined') {
    document.addEventListener('alpine:init', () => {
        Alpine.data('mediaListControls', mediaListControlsData);
        Alpine.data('entityListControls', entityListControlsData);
    });
}

if (typeof window !== 'undefined') {
    window.mediaListControlsData = mediaListControlsData;
    window.entityListControlsData = entityListControlsData;
}
