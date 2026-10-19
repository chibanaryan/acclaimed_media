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

    function choose(status) {
        const menu = getMenu();
        const wrapper = activeWrapper;
        close(false);
        if (!menu || !wrapper || typeof htmx === 'undefined') return;
        const url = menu.dataset.url.replace('/0/', '/' + wrapper.dataset.igdbId + '/') +
            '?status=' + status +
            (wrapper.dataset.size === 'large' ? '&size=large' : '');
        // The wrapper as source inherits the body's hx-headers CSRF token.
        htmx.ajax('POST', url, { source: wrapper, target: wrapper, swap: 'outerHTML' });
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
        if (event.key === 'Escape' && activeWrapper) close(true);
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
