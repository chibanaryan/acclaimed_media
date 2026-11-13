/**
 * Keeps a section's tracking id Sets current after an HTMX button swap.
 *
 * Games and books each solve this by shipping an inline <script> *inside*
 * every swapped button partial, which mutates the global Sets, mirrors the
 * icon into its desktop/mobile twin, and then deletes its own previous
 * copies so they do not accumulate. That last step exists only because of
 * the first. One delegated listener needs none of it, and leaves the swapped
 * markup free of inline script - which is what a Content Security Policy
 * would require if games/csp_middleware.py were ever re-enabled.
 *
 * A page registers what its scope means:
 *
 *   window.MediaTracking.register('album', {
 *       sets: {
 *           own: 'ownedAlbumIds',
 *           listened: 'listenedAlbumIds',
 *           want: 'wantToListenAlbumIds'
 *       },
 *       event: 'album-status-changed'
 *   });
 *
 * `sets` maps each tracked status to the global Set holding its ids. The
 * states are exclusive, so a toggle adds the id to its status's Set and
 * removes it from every other; `none` has no Set and so clears them all.
 * A section may track any number of states, and nothing here knows about
 * albums, games or books. The button itself
 * carries data-tracking-scope, data-item-id and data-status, which is all
 * the listener reads.
 */
(function () {
    'use strict';

    const MediaTracking = {
        _scopes: {},
        _installed: false,

        /**
         * Declare how a scope's state is stored. Safe to call more than once.
         */
        register(scope, config) {
            this._scopes[scope] = config;
            this._install();
        },

        _install() {
            if (this._installed) return;
            this._installed = true;
            // htmx:afterRequest, not htmx:afterSwap. With hx-swap="outerHTML"
            // the swap *replaces* the target, so by the time either event
            // fires `detail.target` is the detached old element, still
            // carrying its pre-swap data-status. Reading the new state off
            // it leaves the Sets one toggle behind for ever. afterRequest
            // fires after the swap, and says whether it succeeded.
            document.addEventListener('htmx:afterRequest', (event) => {
                this._onToggle(event);
            });
            // Whether the reader was in the button's menu when they chose:
            // the swap replaces the wrapper and its menu, and focus fell to
            // the top of the page, so a keyboard reader started over
            document.addEventListener('htmx:beforeRequest', (event) => {
                const target = event.detail && event.detail.target;
                this._hadFocus = Boolean(
                    target && target.dataset && target.dataset.trackingScope &&
                    target.contains(document.activeElement)
                );
            });
            // The dropdown is a menu, and a menu is walked with the arrow
            // keys. Its button said aria-haspopup from the start; until
            // 2026-11-12 nothing behind it had a role or took a key.
            document.addEventListener('keydown', (event) => {
                this._onMenuKey(event);
            });
            // Capture: the wrapper stops a click's propagation, so that a
            // mobile row does not navigate
            document.addEventListener('click', (event) => {
                this._onTriggerClick(event);
            }, true);
        },

        /**
         * Where an arrow, Home or End takes focus among `length` menu items
         * from index `at` (-1 on the button, above the first).
         */
        nextIndex(key, at, length) {
            if (key === 'Home') return 0;
            if (key === 'End') return length - 1;
            if (key === 'ArrowUp') return at <= 0 ? length - 1 : at - 1;
            return (at + 1) % length;
        },

        /** The menu's items that can be seen: none while it is closed. */
        _menuItems(wrapper) {
            return Array.from(wrapper.querySelectorAll('[role="menuitem"]')).filter(
                (item) => item.offsetParent !== null
            );
        },

        /**
         * The keys of a menu button and its menu (WAI-ARIA's pattern), for
         * whichever wrapper holds the key's target. Nothing is remembered
         * between keys.
         */
        _onMenuKey(event) {
            const key = event.key;
            if (!['ArrowDown', 'ArrowUp', 'Home', 'End', 'Tab', 'Escape'].includes(key)) {
                return;
            }
            // A chord is the browser's or the system's: Cmd+Down is "the
            // bottom of the page", not "the next item"
            if (event.metaKey || event.ctrlKey || event.altKey) return;
            const target = event.target;
            const wrapper = target && target.closest &&
                target.closest('.tracking-button-wrapper');
            if (!wrapper) return;
            const trigger = wrapper.querySelector('.tracking-button');
            const items = this._menuItems(wrapper);
            const at = items.indexOf(target);

            if (key === 'Escape' || key === 'Tab') {
                // Only from inside the menu: on the button, Tab is Tab
                if (at === -1) return;
                // Alpine closes on Escape itself. Tab leaves a menu: back to
                // its button, from where the next Tab carries on. The menu's
                // items are still on screen while it fades, so the browser's
                // own Tab would land on the next of them.
                if (key === 'Tab') {
                    event.preventDefault();
                    window.dispatchEvent(new CustomEvent('close-tracking-dropdowns'));
                }
                if (trigger) trigger.focus();
                return;
            }

            if (!items.length) {
                // Closed: an arrow on the button opens it, as Enter does.
                // Not in quick-mark mode, where a click on the button
                // applies the picked status and opens nothing: the arrow
                // would mark the item, and the next press clear it.
                if (target === trigger && (key === 'ArrowDown' || key === 'ArrowUp') &&
                        !this._marks(wrapper)) {
                    event.preventDefault();
                    trigger.click();
                }
                return;
            }
            if (at === -1 && target !== trigger) return;
            event.preventDefault();
            items[this.nextIndex(key, at, items.length)].focus();
        },

        /**
         * A menu opened from the keyboard starts on its first item. A
         * pointer's click leaves focus where it is.
         */
        _onTriggerClick(event) {
            if (event.detail !== 0) return;
            const trigger = event.target && event.target.closest &&
                event.target.closest('.tracking-button');
            if (!trigger || trigger.getAttribute('aria-expanded') === 'true') return;
            const wrapper = trigger.closest('.tracking-button-wrapper');
            // In quick-mark mode the click marks and no menu is coming
            if (wrapper && !this._marks(wrapper)) this._focusFirstItem(wrapper, 10);
        },

        /** Whether a click on this wrapper's button marks, in quick-mark mode. */
        _marks(wrapper) {
            return Boolean(
                window.QuickMark && window.QuickMark.active(wrapper.dataset.trackingScope)
            );
        },

        /** Focus the first item once Alpine has shown the menu. */
        _focusFirstItem(wrapper, framesLeft) {
            const items = this._menuItems(wrapper);
            if (items.length) {
                items[0].focus();
            } else if (framesLeft > 0) {
                requestAnimationFrame(() => this._focusFirstItem(wrapper, framesLeft - 1));
            }
        },

        /**
         * The status this request asked for, from its own URL.
         *
         * Taken from the request rather than the DOM because the request is
         * unambiguous: the replaced element holds the old status, and its
         * desktop/mobile twin holds the old one too, so neither says what
         * just happened. `?status=` is the toggle vocabulary the shared
         * button template always writes.
         */
        _requestedStatus(detail) {
            const path =
                (detail.pathInfo && detail.pathInfo.requestPath) ||
                (detail.requestConfig && detail.requestConfig.path) ||
                '';
            const match = /[?&]status=([a-z]+)/.exec(path);
            return match ? match[1] : null;
        },

        _onToggle(event) {
            const detail = event.detail || {};
            // A failed toggle changed nothing on the server, so it must not
            // change anything here either.
            if (!detail.successful) return;

            const target = detail.target;
            if (!target || !target.dataset || !target.dataset.trackingScope) return;

            const scope = target.dataset.trackingScope;
            const config = this._scopes[scope];
            if (!config) return;

            // Identity only: these attributes do not change across a swap.
            const itemId = Number(target.dataset.itemId);
            const status = this._requestedStatus(detail);
            if (!itemId || !status) return;

            this._updateSets(config, itemId, status);
            this._mirrorTwins(scope, itemId, status, target.dataset.size);
            if (this._hadFocus) this._refocus(scope, itemId, target.dataset.size);

            window.dispatchEvent(
                new CustomEvent(config.event, { detail: { id: itemId, status } })
            );
        },

        _updateSets(config, itemId, status) {
            Object.keys(config.sets || {}).forEach((setStatus) => {
                const ids = window[config.sets[setStatus]];
                if (!ids) return;
                if (setStatus === status) {
                    ids.add(itemId);
                } else {
                    ids.delete(itemId);
                }
            });
        },

        /**
         * Put focus back on the item's button, in the row half on screen,
         * unless the reader has moved it somewhere already.
         */
        _refocus(scope, itemId, size) {
            this._hadFocus = false;
            const active = document.activeElement;
            if (active && active !== document.body) return;
            const selector =
                '[data-tracking-scope="' + scope + '"][data-item-id="' + itemId + '"]';
            const wrapper = Array.from(document.querySelectorAll(selector)).find(
                (el) => (!size || el.dataset.size === size) && el.offsetParent !== null
            );
            const button = wrapper && wrapper.querySelector('.tracking-button');
            if (button) button.focus();
        },

        /**
         * Copy the new icon into the same item's other renderings.
         *
         * A row exists twice, once per breakpoint, and only one is visible,
         * so the hidden one would otherwise keep the old icon until a
         * reload. Only one of them was swapped; the freshly rendered one is
         * the attached wrapper already reading the new status, and it is the
         * icon to copy from.
         *
         * Twins are matched on data-size as well as the item: games' version
         * matches on the item alone, so a toggle from a detail page's large
         * button would write its oversized icon into a row.
         */
        _mirrorTwins(scope, itemId, status, size) {
            const selector =
                '[data-tracking-scope="' + scope + '"][data-item-id="' + itemId + '"]';
            const wrappers = Array.from(document.querySelectorAll(selector));

            const fresh = wrappers.find((el) => el.dataset.status === status);

            const sourceButton = fresh && fresh.querySelector('.tracking-button');
            const sourceMenu = fresh && fresh.querySelector('ul');
            wrappers.forEach((twin) => {
                if (twin === fresh) return;
                if (size && twin.dataset.size !== size) return;
                // The whole button, not its first span: a row the engine
                // rendered holds one span per state, so writing the first
                // left the old state's icon showing beside the new one
                const button = twin.querySelector('.tracking-button');
                if (sourceButton && button) {
                    button.innerHTML = sourceButton.innerHTML;
                    ['data-tip', 'aria-label'].forEach((name) => {
                        const value = sourceButton.getAttribute(name);
                        if (value !== null) button.setAttribute(name, value);
                    });
                }
                // And its menu, which offers only the states the item is
                // not in. Its items carry no Alpine, only hx-post.
                const menu = twin.querySelector('ul');
                if (sourceMenu && menu) {
                    menu.innerHTML = sourceMenu.innerHTML;
                    if (window.htmx) window.htmx.process(menu);
                }
                twin.dataset.status = status;
            });
        }
    };

    window.MediaTracking = MediaTracking;
})();
