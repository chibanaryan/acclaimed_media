/**
 * Load More for the entity lists: developers, games' source lists, authors.
 *
 * Each page used to carry its own inline copy of this. Every copy built its
 * address from `window.location`, appended whatever a 200 held, and moved the
 * button on only from the append partial's `#load-more-meta` - so a response
 * without it (a whole page, from a redirect or a proxy) put its rows in and
 * left the button loading and disabled for good. The rules here are games'
 * (`games/static/games/js/utils-loadmore.js`, `fetchPage` and
 * `appendPageResults`), without its engine.
 *
 * The button says everything this needs:
 *
 *   data-entity-load-more   marks it (games' rankings button is not one)
 *   data-list-url           the list's own address, rendered by the server
 *   data-next-page          the page to ask for next
 *   data-append             JSON pairs: [selector in the response, id of the
 *                           element its matches are appended to]
 *   data-noun               "developers", for "All 1,234 developers loaded"
 *   data-stagger            ms between each new row's entry animation (8)
 *   data-init-alpine        start Alpine on each new element
 *
 * One delegated listener, so a search that swaps the list in needs nothing
 * re-bound.
 */
(function () {
    'use strict';

    /**
     * Fetches the next page of the button's list
     * @param {HTMLElement} button - The list's Load More button
     * @returns {Promise<{doc: Document, meta: Object}>}
     */
    async function fetchNextPage(button) {
        // The list's own address: a search's swap moves the URL, and the
        // page after this list's is not the page after the URL's
        const listUrl = new URL(button.dataset.listUrl, window.location.origin);
        listUrl.searchParams.set('page', button.dataset.nextPage);
        listUrl.searchParams.set('append', 'true');

        const response = await fetch(listUrl.pathname + listUrl.search, {
            cache: 'no-store',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'HX-Request': 'true'
            }
        });
        if (!response.ok) throw new Error('Failed to load page ' + button.dataset.nextPage);

        const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
        // Only the append partial carries the meta. Any other 200 is not this
        // page, and its rows would go in with nothing to move the button on
        const metaScript = doc.getElementById('load-more-meta');
        if (!metaScript) {
            throw new Error('Page ' + button.dataset.nextPage + ' came back without its meta');
        }
        return { doc, meta: JSON.parse(metaScript.textContent) };
    }

    /**
     * Moves the button past the page just appended, or retires it
     * @param {HTMLElement} button - The list's Load More button
     * @param {Object} meta - The page's `#load-more-meta`
     */
    function advanceButton(button, meta) {
        button.classList.remove('loading');
        if (!meta.hasMore) {
            const noun = button.dataset.noun || 'results';
            button.parentElement.innerHTML =
                '<div class="text-base-content/85 text-center">All ' +
                meta.totalCount.toLocaleString() + ' ' + noun + ' loaded</div>';
            return;
        }
        button.disabled = false;
        button.dataset.nextPage = meta.nextPage;
        button.dataset.loaded = meta.loadedCount;
        const text = button.querySelector('.load-more-text');
        if (text) {
            text.textContent = 'Load More (' + meta.remainingCount.toLocaleString() + ' remaining)';
        }
    }

    /**
     * The counts in the heading, from the page's meta
     * @param {Object} meta - The page's `#load-more-meta`
     */
    function updateCounts(meta) {
        const loaded = document.getElementById('loaded-count');
        if (loaded) loaded.textContent = meta.loadedCount.toLocaleString();
        const lists = document.getElementById('loaded-list-count');
        if (lists && meta.totalListCount !== undefined) {
            lists.textContent = meta.totalListCount.toLocaleString();
        }
        // The heading is no live region: say the new count (utils-base.js)
        const heading = document.getElementById('results-count');
        if (heading && typeof announce === 'function') announce(heading.textContent);
    }

    async function loadMore(button) {
        if (!button.dataset.nextPage || button.classList.contains('loading')) return;
        button.classList.add('loading');
        button.disabled = true;

        let appended = false;
        try {
            const { doc, meta } = await fetchNextPage(button);
            // A search replaced the button, and with it the list this page
            // extends: its rows would go in under another list
            if (!button.isConnected) return;

            const added = [];
            const stagger = Number(button.dataset.stagger || 8);
            JSON.parse(button.dataset.append).forEach(([selector, targetId]) => {
                const target = document.getElementById(targetId);
                if (!target) return;
                doc.querySelectorAll(selector).forEach((element, index) => {
                    element.classList.add('game-row-enter');
                    element.style.animationDelay = (index * stagger) + 'ms';
                    target.appendChild(element);
                    added.push(element);
                    appended = true;
                });
            });

            // The rows are in, so the button moves past them before anything
            // else can throw: left asking for this page, a retry appended it
            // twice
            advanceButton(button, meta);

            // What remains only dresses the rows; a failure is logged
            const finishing = [() => updateCounts(meta)];
            if ('initAlpine' in button.dataset) {
                finishing.push(() => {
                    if (window.Alpine) added.forEach(element => window.Alpine.initTree(element));
                });
            }
            finishing.forEach(step => {
                try {
                    step();
                } catch (err) {
                    console.error('Load more error:', err);
                }
            });
        } catch (err) {
            console.error('Load more error:', err);
            // Rows that went in stay, and the button with them stays off
            // rather than asking for the same page again
            if (!appended) {
                button.classList.remove('loading');
                button.disabled = false;
            }
        }
    }

    document.addEventListener('click', event => {
        const button = event.target.closest('.load-more-button[data-entity-load-more]');
        if (button) loadMore(button);
    });
})();
