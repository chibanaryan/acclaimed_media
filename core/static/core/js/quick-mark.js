/**
 * Quick-mark mode: one click on a tracking button applies a chosen status.
 *
 * Marking a collection through the per-button menu costs two clicks an
 * item - open the menu, pick the status - which adds up for someone working
 * down a ranking marking everything they own. The picker
 * (core/includes/_quick_mark_picker.html) sets a mode per scope; while one
 * is on, a click on that scope's button posts the mode's status directly.
 * Clicking an item already in that status clears it, so a mis-click is
 * undone the same way it was made. "Off" restores the menu.
 *
 * The mode lives in localStorage, so it survives a reload and the HTMX
 * re-render of the controls the picker sits in. It only takes effect while
 * a picker for the scope is on the page: a detail page, which has no picker,
 * keeps the menu whatever the stored mode says.
 *
 * Two kinds of button use it. The shared tracking button
 * (core/includes/_tracking_button.html) is handled here, by a capture-phase
 * listener that runs ahead of the button's own Alpine handler and of the
 * wrapper's stopPropagation, and posts to the wrapper's data-toggle-url.
 * Games' played button has its own shared menu, so played-menu.js asks
 * QuickMark.active() itself before opening it.
 *
 * Either way the post goes out with the wrapper as source and target, as
 * the menus' own do, so the response swaps in through the same path and
 * media-tracking.js / the played sync script keep the id Sets current.
 */
(function () {
    'use strict';

    if (window.QuickMark) return;

    const STORAGE_PREFIX = 'quickMark:';

    function read(scope) {
        try {
            return window.localStorage.getItem(STORAGE_PREFIX + scope) || '';
        } catch (e) {
            return '';
        }
    }

    function write(scope, mode) {
        try {
            if (mode) {
                window.localStorage.setItem(STORAGE_PREFIX + scope, mode);
            } else {
                window.localStorage.removeItem(STORAGE_PREFIX + scope);
            }
        } catch (e) {
            // Private browsing can refuse storage; the mode then lasts for
            // this page only, which is still what was asked for.
        }
    }

    const QuickMark = {
        _modes: {},

        /** The stored mode for a scope, '' when off. */
        get(scope) {
            if (!(scope in this._modes)) this._modes[scope] = read(scope);
            return this._modes[scope];
        },

        /** Set a scope's mode ('' for off) and tell every picker. */
        set(scope, mode) {
            this._modes[scope] = mode || '';
            write(scope, this._modes[scope]);
            this._syncRootClass(scope);
            window.dispatchEvent(new CustomEvent('quick-mark-change', {
                detail: { scope: scope, mode: this._modes[scope] }
            }));
        },

        /**
         * The mode to apply to a click in this scope, or '' to let the
         * button open its menu as usual.
         */
        active(scope) {
            const mode = this.get(scope);
            if (!mode) return '';
            const picker = document.querySelector(
                '[data-quick-mark-scope="' + scope + '"]'
            );
            return picker ? mode : '';
        },

        /** The status a click should set: the mode, or none to undo it. */
        next(current, mode) {
            return current === mode ? 'none' : mode;
        },

        /**
         * Post `mode` (or its undo) for one wrapper. Returns whether a
         * request went out.
         */
        mark(wrapper, url, mode) {
            if (!wrapper || !url || typeof htmx === 'undefined') return false;
            // One request at a time per button: the swap replaces the
            // wrapper, so a second click before then would act on the old
            // status.
            if (wrapper.classList.contains('htmx-request')) return false;

            const current = wrapper.dataset.status || 'none';
            const status = this.next(current, mode);
            if (status === current) return false;

            const size = wrapper.dataset.size === 'large' ? '&size=large' : '';
            // The wrapper as source inherits the body's hx-headers CSRF token.
            htmx.ajax('POST', url + '?status=' + status + size, {
                source: wrapper, target: wrapper, swap: 'outerHTML'
            });
            return true;
        },

        _syncRootClass(scope) {
            const root = document.documentElement;
            root.classList.toggle('quick-mark-' + scope, Boolean(this.active(scope)));
        },

        _syncAllRootClasses() {
            document.querySelectorAll('[data-quick-mark-scope]').forEach((el) => {
                this._syncRootClass(el.dataset.quickMarkScope);
            });
        },

        _install() {
            // Capture phase: the button's Alpine @click would open the menu
            // and the wrapper stops propagation in the bubble phase, so a
            // bubbling listener would never see the click at all.
            document.addEventListener('click', (event) => {
                const button = event.target.closest('.tracking-button');
                const wrapper =
                    button && button.closest('.tracking-button-wrapper[data-tracking-scope]');
                if (!wrapper) return;

                const mode = this.active(wrapper.dataset.trackingScope);
                if (!mode) return;

                event.preventDefault();
                event.stopPropagation();
                // The second click of a double-click would undo the first.
                if (event.detail >= 2) return;
                this.mark(wrapper, wrapper.dataset.toggleUrl, mode);
            }, true);

            // The picker arrives with the page and again with every results
            // swap, so the cursor class follows it rather than the load.
            const sync = () => this._syncAllRootClasses();
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', sync);
            } else {
                sync();
            }
            document.addEventListener('htmx:afterSettle', sync);
        }
    };

    QuickMark._install();
    window.QuickMark = QuickMark;
})();
