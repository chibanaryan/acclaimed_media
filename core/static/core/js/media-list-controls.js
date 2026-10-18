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

/** The heading's time window, as core/services/titles.py builds it. */
function buildTimeWindow(start, end, minYear, maxYear) {
    if (start === null || end === null || start === undefined || end === undefined) {
        return '';
    }
    if (start <= minYear && end >= maxYear) return 'All Time';
    if (start === end) return String(start);
    if (start % 10 === 0 && end === start + 9) return 'the ' + start + 's';
    return start + '-' + end;
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
        defaultSort: settings.sort || 'rank',
        _commitTimer: null,
        _popstateListener: null,
        _genresSelectedListener: null,

        init() {
            this._applyViewMode();
            this._popstateListener = () => this._syncFromUrl();
            window.addEventListener('popstate', this._popstateListener);

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
            clearTimeout(this._commitTimer);
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
            clearTimeout(this._commitTimer);
            this._commitTimer = setTimeout(() => this.commit(), 250);
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
         * Games' `togglePlayedStatus` with the key supplied, so the shared
         * status control can drive whichever parameter a section uses.
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
            window.dispatchEvent(new CustomEvent('year-reset'));
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
            const form = this._form();
            if (form) {
                const artists = form.querySelector('[name="artists"]');
                if (artists) artists.value = '';
            }
            window.dispatchEvent(new CustomEvent('year-reset'));
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
            return (
                this.filters.start > this.minYear || this.filters.end < this.maxYear
            );
        },

        // -- plumbing --------------------------------------------------------

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
         * The heading, composed from the filter state.
         *
         * Mirrors `music.views._filter_title`, as games' `_buildDynamicTitle`
         * mirrors its own server-side builder. The heading sits outside the
         * swapped results container, so neither path gets it for free: the
         * server sends it back out of band, and this sets it directly when
         * filtering happens in the browser.
         */
        buildTitle() {
            if (this.filters.q) {
                return `${settings.titleSearchNoun || 'Items'} matching \u201c` +
                    `${this.filters.q}\u201d`;
            }

            const names = this.filters.genres
                .map(id => {
                    const genre = this.genres.find(
                        entry => String(entry.id) === String(id)
                    );
                    return genre ? genre.name : null;
                })
                .filter(Boolean);
            const genreLabel = names.length ? ' ' + joinNames(names) : '';

            const window_ = buildTimeWindow(
                this.filters.start,
                this.filters.end,
                this.minYear,
                this.maxYear
            );
            const timeSuffix = window_ ? ' of ' + window_ : '';

            // Mirrors the status suffix `_filter_title` appends. Without it
            // the heading would change the moment filtering moved from the
            // server to the browser.
            const statuses = this.filters[statusKey] || [];
            const labels = (settings.statusOptions || [])
                .filter(option => statuses.includes(option.value))
                .map(option => option.title);
            const statusSuffix = labels.length ? ': ' + joinNames(labels) : '';

            const noun = settings.titleNoun || 'Items';
            return `Most Acclaimed${genreLabel} ${noun}` +
                `${timeSuffix}${statusSuffix}`;
        },

        /** @private */
        _applyTitle() {
            const title = this.buildTitle();
            ['search-title-text', 'search-title-mobile-text'].forEach(id => {
                const el = document.getElementById(id);
                if (el) el.textContent = title;
            });
            // The document title is composed from the same heading
            // server-side, so it has to follow the heading here too -
            // otherwise the tab, a bookmark and a shared link all keep
            // whatever the filter state was when the page was loaded.
            if (window.documentTitleSuffix) {
                document.title = title + window.documentTitleSuffix;
            }
        },

        /**
         * Write the filter state onto the form and announce it.
         *
         * A year range covering everything is written as empty, because
         * that is how the server spells "no year filter" - the grid spells
         * it as the full range.
         */
        commit() {
            const form = this._form();
            if (!form) return;

            const setField = (name, value) => {
                const field = form.querySelector(`[name="${name}"]`);
                if (field) field.value = value;
            };
            const hasYears = this.hasYearFilter();
            setField('q', this.filters.q || '');
            setField('start', hasYears ? this.filters.start : '');
            setField('end', hasYears ? this.filters.end : '');
            setField('genres', this.filters.genres.join(','));
            setField(statusKey, (this.filters[statusKey] || []).join(','));
            setField('sort', this.filters.sort);
            setField('dir', this.filters.sortDirection);

            this._applyTitle();
            form.dispatchEvent(new Event('change', { bubbles: true }));
        },

        /**
         * Re-read the filter state from the URL after a Back/Forward.
         * @private
         */
        _syncFromUrl() {
            const params = new URLSearchParams(window.location.search);
            const number = (name, fallback) => {
                const parsed = parseInt(params.get(name), 10);
                return Number.isFinite(parsed) ? parsed : fallback;
            };
            this.filters.q = params.get('q') || '';
            this.filters.start = number('start', this.minYear);
            this.filters.end = number('end', this.maxYear);
            this.filters.genres = (params.get('genres') || '')
                .split(',')
                .filter(Boolean);
            this.filters[statusKey] = (params.get(statusKey) || '')
                .split(',')
                .filter(Boolean);
            this.filters.sort = params.get('sort') || this.defaultSort;
            this.filters.sortDirection = params.get('dir') || 'asc';
            this._applyTitle();
            window.dispatchEvent(new CustomEvent('year-reset'));
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
 * defaultDir, and extraFields - the names of other inputs whose values have
 * to ride along with the request.
 */
function entityListControlsData(config) {
    const settings = config || {};
    const defaultSort = settings.defaultSort || settings.sort || '';
    const defaultDir = settings.defaultDir || 'desc';

    return {
        sort: settings.sort || defaultSort,
        sortDirection: settings.dir || defaultDir,

        updateSort(newSort) {
            if (newSort === this.sort) return;
            this.sort = newSort;
            // Each sort has a direction that is obviously right first time:
            // a name reads A-Z, a count or a year reads biggest first. The
            // games source-lists page picks the same way.
            const ascending = settings.ascendingSorts || ['name', 'alpha', 'order', 'rank'];
            this.sortDirection = ascending.indexOf(newSort) === -1 ? 'desc' : 'asc';
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
            setParam('dir', this.sortDirection, defaultDir);
            url.searchParams.delete('page');
            window.history.pushState({}, '', url);

            const values = { sort: this.sort, dir: this.sortDirection };
            (settings.extraFields || []).forEach(name => {
                const field = document.querySelector(`[name="${name}"]`);
                if (field) values[name] = field.value;
            });

            if (typeof htmx !== 'undefined') {
                htmx.ajax('GET', settings.url, {
                    target: settings.target,
                    swap: 'innerHTML',
                    values
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
