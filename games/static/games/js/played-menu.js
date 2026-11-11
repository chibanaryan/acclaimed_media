/**
 * The game status menu, one per page, shared by every played button.
 *
 * Each button used to carry its own menu: an Alpine component and three
 * hx-post items, rendered twice per game for the desktop and mobile row
 * halves. Now a button is only its trigger, and this script opens
 * #played-menu (games/includes/_played_menu.html) beside whichever one was
 * clicked, showing the statuses other than the button's own, and posts the
 * toggle with htmx. The response replaces the wrapper and carries the sync
 * script that updates the global Sets and the button's twin.
 *
 * The wrapper stops click propagation so the mobile row does not navigate,
 * so this listens in the capture phase, ahead of that.
 *
 * With a quick-mark mode on (core/js/quick-mark.js, set from the picker in
 * the results header) a click posts that status straight away instead of
 * opening the menu.
 */
(function() {
    'use strict';

    if (window._playedMenuInitialized) return;
    window._playedMenuInitialized = true;

    let activeWrapper = null;

    function getMenu() {
        return document.getElementById('played-menu');
    }

    // The bottom edge of a fixed bar across the top of the viewport, if any.
    function topInset() {
        const bar = document.getElementById('header');
        if (!bar || getComputedStyle(bar).position !== 'fixed') return 0;
        const rect = bar.getBoundingClientRect();
        return rect.height && rect.bottom > 0 ? rect.bottom : 0;
    }

    function trigger(wrapper) {
        return wrapper && wrapper.querySelector('.played-button');
    }

    function close(restoreFocus) {
        const menu = getMenu();
        if (menu) menu.classList.add('hidden');
        const button = trigger(activeWrapper);
        if (button) {
            button.setAttribute('aria-expanded', 'false');
            if (restoreFocus) button.focus();
        }
        activeWrapper = null;
    }

    function open(wrapper, focusFirst) {
        const menu = getMenu();
        if (!menu) return;
        const status = wrapper.dataset.status || 'none';
        menu.querySelectorAll('li[data-status]').forEach(function(item) {
            item.classList.toggle('hidden', item.dataset.status === status);
        });

        // Measure while invisible, then place above the button (below for
        // the large one on the detail page, as the per-button menu was) -
        // or below whenever the space above is under a fixed top bar (the
        // mobile nav) or off screen.
        menu.style.visibility = 'hidden';
        menu.classList.remove('hidden');
        const rect = wrapper.getBoundingClientRect();
        const above = rect.top - menu.offsetHeight - 4;
        const below = wrapper.dataset.size === 'large' || above < topInset();
        const top = below ? rect.bottom + 4 : above;
        menu.style.top = (top + window.scrollY) + 'px';
        menu.style.left = (rect.left + window.scrollX) + 'px';
        menu.style.visibility = '';

        activeWrapper = wrapper;
        trigger(wrapper).setAttribute('aria-expanded', 'true');
        if (focusFirst) {
            const first = menu.querySelector('li:not(.hidden) button');
            if (first) first.focus();
        }
    }

    function toggleUrl(wrapper) {
        const menu = getMenu();
        return menu.dataset.url.replace('/0/', '/' + wrapper.dataset.igdbId + '/');
    }

    // The button that replaced `wrapper`'s, in the row half on screen
    function freshTrigger(wrapper) {
        const size = wrapper.dataset.size || '';
        const candidates = document.querySelectorAll(
            '.played-button-wrapper[data-igdb-id="' + wrapper.dataset.igdbId + '"]'
        );
        for (const candidate of candidates) {
            if ((candidate.dataset.size || '') === size && candidate.offsetParent !== null) {
                return trigger(candidate);
            }
        }
        return null;
    }

    function post(wrapper, status, refocus) {
        if (typeof htmx === 'undefined') return;
        const url = toggleUrl(wrapper) +
            '?status=' + status +
            (wrapper.dataset.size === 'large' ? '&size=large' : '');
        // The wrapper as source inherits the body's hx-headers CSRF token.
        const swapped = htmx.ajax('POST', url, { source: wrapper, target: wrapper, swap: 'outerHTML' });
        // A keyboard reader is put back on the button: the swap replaced the
        // one they came from, and focus fell to the top of the page
        if (refocus && swapped && typeof swapped.then === 'function') {
            swapped.then(function() {
                const active = document.activeElement;
                if (active && active !== document.body) return;
                const button = freshTrigger(wrapper);
                if (button) button.focus();
            });
        }
    }

    function choose(status) {
        const menu = getMenu();
        const wrapper = activeWrapper;
        // Chosen from the keyboard if the menu holds focus
        const refocus = Boolean(menu && menu.contains(document.activeElement));
        close(refocus);
        if (!menu || !wrapper) return;
        post(wrapper, status, refocus);
    }

    // The menu's items in order, the hidden one (the current status) left out
    function items() {
        const menu = getMenu();
        return menu ? Array.from(menu.querySelectorAll('li:not(.hidden) button')) : [];
    }

    // The quick-mark mode for games, or '' when off or not on this page.
    function quickMode() {
        return window.QuickMark ? window.QuickMark.active('game') : '';
    }

    document.addEventListener('click', function(event) {
        const menu = getMenu();
        if (!menu) return;

        const item = event.target.closest('#played-menu li[data-status]');
        if (item) {
            choose(item.dataset.status);
            return;
        }

        const button = event.target.closest('.played-button');
        const wrapper = button && button.closest('.played-button-wrapper');
        if (wrapper) {
            const mode = quickMode();
            if (mode) {
                close(false);
                // The second click of a double-click would undo the first.
                if (event.detail < 2) {
                    window.QuickMark.mark(wrapper, toggleUrl(wrapper), mode);
                }
                return;
            }
            const reopen = wrapper !== activeWrapper;
            close(false);
            // A keyboard activation reports no pointer, so it gets focus moved
            // into the menu; a mouse click leaves focus where it was.
            if (reopen) open(wrapper, event.detail === 0);
            return;
        }

        if (activeWrapper && !menu.contains(event.target)) close(false);
    }, true);

    document.addEventListener('keydown', function(event) {
        if (!activeWrapper) return;
        if (event.key === 'Escape') {
            close(true);
            return;
        }
        const menu = getMenu();
        if (!menu || !menu.contains(event.target)) return;
        // A menu is walked with the arrow keys (role="menu"), and Tab leaves
        // it: back to its button, from where Tab carries on. It stayed open,
        // floating, with focus gone on through the page.
        if (event.key === 'Tab') {
            close(true);
            return;
        }
        if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            const list = items();
            if (!list.length) return;
            event.preventDefault();
            const step = event.key === 'ArrowDown' ? 1 : -1;
            const at = list.indexOf(document.activeElement);
            list[(at + step + list.length) % list.length].focus();
        }
    });

    // A position computed from the button goes stale when the layout moves.
    window.addEventListener('resize', function() {
        if (activeWrapper) close(false);
    });
    document.addEventListener('htmx:beforeSwap', function(event) {
        if (activeWrapper && event.detail.target &&
            event.detail.target.contains(activeWrapper)) {
            close(false);
        }
    });
})();
