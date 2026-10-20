/**
 * Base Media List Renderer - Client-Side Rendering Foundation
 *
 * Provides shared functionality for rendering media lists (games, books, etc.)
 * using DOM template cloning. Concrete renderers should extend this class.
 *
 * This ensures a single source of truth for HTML structure while allowing
 * media-specific customization.
 */

/**
 * BaseMediaListRenderer - Abstract base class for media list rendering
 *
 * Usage:
 *   class GameListRenderer extends BaseMediaListRenderer {
 *       constructor(filterEngine) {
 *           super(filterEngine);
 *           // Game-specific initialization
 *       }
 *   }
 */
class BaseMediaListRenderer {
    /**
     * @param {Object} filterEngine - Engine with reference data for expanding items
     */
    constructor(filterEngine) {
        this.engine = filterEngine;
        this.PAGE_SIZE = 100;
        // How many rows either side of the target a jump renders.
        this.JUMP_RADIUS = 50;
        // The class of the element grid cards are rendered into.
        this.GRID_CLASS = 'media-grid';
        this.currentItems = [];
        // The slice of currentItems on the page: 0-based, end exclusive.
        // A jump can leave it starting part-way down the list, which is
        // what Load Previous fills back in.
        this.windowStart = 0;
        this.windowEnd = 0;
        this.highlightId = null;
        this._csrfToken = null;
        this._templates = null;
    }

    /**
     * Get CSRF token from cookie
     * @protected
     */
    _getCsrfToken() {
        if (this._csrfToken) return this._csrfToken;
        const match = document.cookie.match(/csrftoken=([^;]+)/);
        this._csrfToken = match ? match[1] : '';
        return this._csrfToken;
    }

    /**
     * Fill a data slot with text content
     * @protected
     */
    _fillSlot(container, slotName, value) {
        const el = container.querySelector(`[data-slot="${slotName}"]`);
        if (!el) return null;
        if (value !== undefined && value !== null) {
            el.textContent = value;
        }
        return el;
    }

    /**
     * Escape HTML special characters
     * @protected
     */
    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text || '';
        return div.innerHTML;
    }

    /**
     * Initialize templates from DOM - override in subclass
     * Called lazily on first render
     * @protected
     */
    _initTemplates() {
        if (this._templates) return;
        // Subclasses should override to initialize their specific templates
        this._templates = {};
    }

    /**
     * Render a single desktop row - override in subclass
     * @protected
     * @returns {Element} The rendered desktop row element
     */
    _renderDesktopRow(item, index, showRank) {
        throw new Error('Subclasses must implement _renderDesktopRow');
    }

    /**
     * Render a single mobile row - override in subclass
     * @protected
     * @returns {Element} The rendered mobile row element
     */
    _renderMobileRow(item, index, showRank) {
        throw new Error('Subclasses must implement _renderMobileRow');
    }

    /**
     * Render a single grid card - override in subclass
     * @protected
     * @returns {Element} The rendered grid card element
     */
    _renderGridCard(item, index, showRank) {
        throw new Error('Subclasses must implement _renderGridCard');
    }

    /**
     * Render items as DOM fragment
     * @protected
     * @param {string} viewMode - 'list' or 'grid'
     * @returns {DocumentFragment}
     */
    _renderItems(items, showRank, startIndex, viewMode = 'list') {
        const fragment = document.createDocumentFragment();

        if (viewMode === 'grid') {
            const gridContainer = document.createElement('div');
            gridContainer.className = this.GRID_CLASS;

            items.forEach((item, i) => {
                const index = startIndex + i;
                const card = this._renderGridCard(item, index, showRank);
                if (card) gridContainer.appendChild(card);
            });

            fragment.appendChild(gridContainer);
        } else {
            items.forEach((item, i) => {
                const index = startIndex + i;
                const desktopRow = this._renderDesktopRow(item, index, showRank);
                const mobileRow = this._renderMobileRow(item, index, showRank);
                if (desktopRow) fragment.appendChild(desktopRow);
                if (mobileRow) fragment.appendChild(mobileRow);
            });
        }

        return fragment;
    }

    /**
     * Render media list to container
     *
     * @param {Array} items - Items to render
     * @param {HTMLElement} container - Container element
     * @param {Object} options - Render options
     * @param {string} [options.showRank='alltime'] - 'alltime', 'filtered', or 'none'
     * @param {number} [options.highlightId] - Item ID to highlight
     * @param {boolean} [options.append=false] - Append to existing content
     * @param {string} [options.viewMode='list'] - 'list' or 'grid'
     */
    render(items, container, options = {}) {
        const {
            showRank = 'filtered',
            highlightId = null,
            append = false,
            viewMode = 'list'
        } = options;

        this.currentItems = items;
        this.highlightId = highlightId;
        this.windowStart = 0;
        this.windowEnd = Math.min(this.PAGE_SIZE, items.length);
        this._currentViewMode = viewMode;
        this._currentShowRank = showRank;

        if (!append) {
            container.innerHTML = '';
        }

        // Render first page
        const pageItems = items.slice(0, this.PAGE_SIZE);
        const fragment = this._renderItems(pageItems, showRank, 1, viewMode);

        container.appendChild(fragment);

        // Reinitialize HTMX for dynamically rendered content
        if (typeof htmx !== 'undefined') {
            htmx.process(container);
        }

        // Handle highlighting
        if (highlightId) {
            this._scrollToHighlight(highlightId, viewMode);
        }
    }

    /**
     * Take over a list the server rendered, without re-rendering it.
     *
     * The server always renders from the top, so the window is the first
     * `renderedCount` items.
     * @param {Array} items - The whole result set, in page order
     * @param {number} renderedCount - How many of them are on the page
     */
    adopt(items, renderedCount) {
        this.currentItems = items;
        this.windowStart = 0;
        this.windowEnd = Math.min(Math.max(renderedCount, 0), items.length);
    }

    /**
     * Where the window stands, for redrawing the count and both buttons.
     * `loaded` is how many rows are on the page, not how far down they go.
     * @returns {Object}
     */
    windowState() {
        const total = this.currentItems.length;
        const start = this.windowStart;
        const end = this.windowEnd;
        const hasMore = end < total;
        return {
            start,
            end,
            loaded: end - start,
            total,
            hasMore,
            remaining: Math.max(total - end, 0),
            maxLoaded: !hasMore,
            hasPrevious: start > 0,
            previousCount: start
        };
    }

    /**
     * Render items into the container, before or after what is there.
     *
     * In grid mode the cards go into the grid element, which is created if
     * there is none yet.
     * @private
     * @param {Array} items
     * @param {number} startIndex - 1-based position of items[0]
     * @param {Object} options - { showRank, viewMode, prepend }
     */
    _insertItems(container, items, startIndex, options = {}) {
        const { showRank = 'filtered', viewMode = 'list', prepend = false } = options;
        if (!items.length) return;

        let target = container;
        let fragment;
        if (viewMode === 'grid') {
            target = container.querySelector('.' + this.GRID_CLASS);
            if (!target) {
                target = document.createElement('div');
                target.className = this.GRID_CLASS;
                container.appendChild(target);
            }
            fragment = document.createDocumentFragment();
            items.forEach((item, i) => {
                const card = this._renderGridCard(item, startIndex + i, showRank);
                if (card) fragment.appendChild(card);
            });
        } else {
            fragment = this._renderItems(items, showRank, startIndex, viewMode);
        }

        if (prepend) {
            target.insertBefore(fragment, target.firstChild);
        } else {
            target.appendChild(fragment);
        }
    }

    /**
     * Load more items (for Load More button)
     *
     * @param {HTMLElement} container - Container element
     * @param {Object} options - Options
     * @returns {Object} windowState()
     */
    loadMore(container, options = {}) {
        const { showRank = 'filtered' } = options;
        const viewMode = this._currentViewMode || 'list';

        const start = this.windowEnd;
        const end = Math.min(start + this.PAGE_SIZE, this.currentItems.length);
        if (end <= start) return this.windowState();

        // A grid begun after the server's rows (which are not cards) has to
        // hold the whole window, not just the next page.
        const first = viewMode === 'grid' &&
            !container.querySelector('.' + this.GRID_CLASS)
            ? this.windowStart
            : start;

        this._insertItems(container, this.currentItems.slice(first, end), first + 1, {
            showRank,
            viewMode
        });
        this.windowEnd = end;

        if (typeof htmx !== 'undefined') {
            htmx.process(container);
        }

        return this.windowState();
    }

    /**
     * Prepend the page above the window (for Load Previous).
     *
     * Wrap the call in captureScrollAnchor() so the reader stays on the row
     * they were looking at rather than being pushed down by the new ones.
     * @param {HTMLElement} container - Container element
     * @param {Object} options - { showRank }
     * @returns {Object} windowState()
     */
    loadPrevious(container, options = {}) {
        const { showRank = 'filtered' } = options;
        const viewMode = this._currentViewMode || 'list';

        const end = this.windowStart;
        const start = Math.max(end - this.PAGE_SIZE, 0);
        if (end <= start) return this.windowState();

        this._insertItems(container, this.currentItems.slice(start, end), start + 1, {
            showRank,
            viewMode,
            prepend: true
        });
        this.windowStart = start;

        if (typeof htmx !== 'undefined') {
            htmx.process(container);
        }

        return this.windowState();
    }

    /**
     * Decide what a jump to `index` (0-based) needs.
     *
     * - 'scroll': the item is already on the page.
     * - 'extend': the target's neighbourhood touches the window, or is
     *   within a page of it, so the window grows to cover it. No gap is
     *   ever left, and nothing the reader already had is thrown away.
     * - 'replace': anything further away. Only the neighbourhood is
     *   rendered, and Load Previous offers the rows above it.
     * @param {number} index
     * @returns {{mode: string, start: number, end: number}}
     */
    planJump(index) {
        const total = this.currentItems.length;
        const start = this.windowStart;
        const end = this.windowEnd;

        if (index >= start && index < end) {
            return { mode: 'scroll', start, end };
        }

        const wantStart = Math.max(index - this.JUMP_RADIUS, 0);
        const wantEnd = Math.min(index + this.JUMP_RADIUS + 1, total);

        if (end > start &&
            wantStart <= end + this.PAGE_SIZE &&
            wantEnd >= start - this.PAGE_SIZE) {
            return {
                mode: 'extend',
                start: Math.min(start, wantStart),
                end: Math.max(end, wantEnd)
            };
        }
        return { mode: 'replace', start: wantStart, end: wantEnd };
    }

    /**
     * Make the window exactly [start, end).
     *
     * A range that touches the current window is reached by rendering only
     * the missing rows above and below it; any other range replaces the
     * container's contents.
     * @param {HTMLElement} container
     * @param {number} start - 0-based, inclusive
     * @param {number} end - 0-based, exclusive
     * @param {Object} options - { showRank, viewMode }
     */
    showRange(container, start, end, options = {}) {
        const { showRank = 'filtered' } = options;
        const viewMode = options.viewMode || this._currentViewMode || 'list';
        this._currentViewMode = viewMode;

        const touches = this.windowEnd > this.windowStart &&
            start <= this.windowEnd && end >= this.windowStart;
        // The server renders rows, never cards, so a grid cannot be grown
        // from them: it has to be built whole.
        const needsGrid = viewMode === 'grid' &&
            !container.querySelector('.' + this.GRID_CLASS);

        if (!touches || needsGrid) {
            container.innerHTML = '';
            this._insertItems(container, this.currentItems.slice(start, end), start + 1, {
                showRank,
                viewMode
            });
        } else {
            if (start < this.windowStart) {
                this._insertItems(
                    container,
                    this.currentItems.slice(start, this.windowStart),
                    start + 1,
                    { showRank, viewMode, prepend: true }
                );
            }
            if (end > this.windowEnd) {
                this._insertItems(
                    container,
                    this.currentItems.slice(this.windowEnd, end),
                    this.windowEnd + 1,
                    { showRank, viewMode }
                );
            }
        }

        this.windowStart = start;
        this.windowEnd = end;

        if (typeof htmx !== 'undefined') {
            htmx.process(container);
        }
    }

    /**
     * Remember where the first visible item sits, so that content inserted
     * above it can be scrolled past. Returns the function that does so.
     *
     * By hand rather than through CSS scroll anchoring, which Safari lacks.
     * @param {HTMLElement} container
     * @returns {Function}
     */
    captureScrollAnchor(container) {
        const grid = container.querySelector('.' + this.GRID_CLASS);
        const holder = this._currentViewMode === 'grid' && grid ? grid : container;
        const anchor = Array.from(holder.children).find(
            el => el.offsetParent !== null
        );
        if (!anchor) return () => {};

        const before = anchor.getBoundingClientRect().top;
        return () => {
            const shift = anchor.getBoundingClientRect().top - before;
            if (shift) window.scrollBy(0, shift);
        };
    }

    /**
     * Reset pagination
     */
    reset() {
        this.currentItems = [];
        this.windowStart = 0;
        this.windowEnd = 0;
        this.highlightId = null;
    }

    /**
     * Scroll to and highlight an item
     * @protected
     * @param {number} itemId - Item ID to highlight
     * @param {string} viewMode - 'list' or 'grid'
     */
    _scrollToHighlight(itemId, viewMode = 'list') {
        // Subclasses should override with their specific ID patterns
        setTimeout(() => {
            let elementToScroll = null;
            let elementsToHighlight = [];

            if (viewMode === 'grid') {
                const gridElement = document.getElementById('item-' + itemId + '-grid');
                if (gridElement) {
                    elementToScroll = gridElement;
                    elementsToHighlight = [gridElement];
                }
            } else {
                const desktopElement = document.getElementById('item-' + itemId);
                const mobileElement = document.getElementById('item-' + itemId + '-mobile');
                const isDesktop = window.matchMedia('(min-width: 962px)').matches;
                elementToScroll = isDesktop ? desktopElement : mobileElement;

                if (desktopElement) elementsToHighlight.push(desktopElement);
                if (mobileElement) elementsToHighlight.push(mobileElement);
            }

            if (elementToScroll) {
                flashHighlight(elementToScroll, elementsToHighlight);
                // Marked once: rows rendered later (Load More, a jump)
                // should not come back highlighted with no fade
                this.highlightId = null;
            }
        }, 300);
    }

    /**
     * Generate result summary HTML
     * @param {number} loaded - Number of rows on the page
     * @param {number} total - Total count
     * @param {Object} [options] - { start: windowStart, compact: mobile line }
     * @returns {string} HTML string
     */
    getResultSummaryHtml(loaded, total, options = {}) {
        const { start = 0, compact = false } = options;
        // Once a jump has left rows above the window, a bare count would
        // read as "the first N", so name the range instead.
        const shown = start > 0
            ? (start + 1).toLocaleString() + '\u2013' + (start + loaded).toLocaleString()
            : loaded.toLocaleString();
        if (compact) {
            // The mobile line drops the "Showing" and the element id, which
            // only ever belongs to one element on the page.
            return '<span class="loaded-count-value">' + shown + '</span> of ' + total.toLocaleString();
        }
        return 'Showing <span id="loaded-count" class="loaded-count-value">' + shown + '</span> of ' + total.toLocaleString();
    }

    /**
     * Generate load more button HTML
     * @param {Object} state - { hasMore, remaining, maxLoaded }
     * @returns {string} HTML string
     */
    getLoadMoreHtml(state) {
        const { hasMore, remaining, maxLoaded } = state;

        if (maxLoaded || !hasMore) {
            return '<div class="text-base-content/70 text-center">All results loaded</div>';
        }

        return '<button type="button" class="btn btn-ghost load-more-button"><span class="mdi mdi-plus-circle-outline"></span><span class="load-more-text">Load More (' + remaining.toLocaleString() + ' remaining)</span></button>';
    }

    /**
     * Generate the Load Previous button HTML, or nothing at the top.
     * @param {Object} state - windowState()
     * @returns {string} HTML string
     */
    getLoadPreviousHtml(state) {
        const { previousCount = 0 } = state || {};
        if (!previousCount) return '';

        return '<button type="button" class="btn btn-ghost load-previous-button"><span class="mdi mdi-chevron-up" aria-hidden="true"></span><span class="load-previous-text">Load Previous (' + previousCount.toLocaleString() + ' above)</span></button>';
    }
}

// Export for use in other modules
if (typeof window !== 'undefined') {
    window.BaseMediaListRenderer = BaseMediaListRenderer;
}
