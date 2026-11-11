/**
 * Modal Handlers - Contact and Auth modal functionality
 * Loaded via requestIdleCallback for better performance
 *
 * Note: Modals (contactModal, authModal) are in the base layout and are NOT
 * swapped by HTMX. The guard prevents duplicate listener registration while
 * handlers re-query elements to be robust against any future DOM changes.
 *
 * A trigger in the mobile menu needs no help closing it: the menu closes
 * itself on any click inside it (_nav_mobile.html). The code that was here
 * for that read Alpine 2's `__x`, which Alpine 3 does not have.
 */
(function() {
    'use strict';

    // Prevent duplicate listener registration (memory leak fix)
    if (window._modalHandlersInitialized) return;
    window._modalHandlersInitialized = true;

    var SIGNUP_SCREEN = '/auth/modal/signup/?direct=1';

    // Opens the auth modal on the screen at `url`. Elements are re-queried
    // each time, for robustness. Answers whether there was a modal to open.
    function openAuthModal(url) {
        var authModal = document.getElementById('authModal');
        if (!authModal) return false;
        htmx.ajax('GET', url, {target: '#auth-modal-content', swap: 'innerHTML'});
        authModal.showModal();
        return true;
    }

    // Auth modal trigger
    document.addEventListener('click', function(e) {
        var trigger = e.target.closest('.auth-modal-trigger');
        if (trigger) {
            // Check for specific screen to load
            var screen = trigger.dataset.authScreen;
            var url = '/auth/modal/login/';
            if (screen === 'profile') {
                // Add cache-buster to ensure fresh data every time
                url = '/auth/modal/profile/?_=' + Date.now();
            } else if (screen === 'signup') {
                url = SIGNUP_SCREEN;
            }
            if (openAuthModal(url)) e.preventDefault();
        }
    });

    // `/#signup` opens the modal on its sign-up screen: where
    // /accounts/signup/ redirects a signed-out visitor, so that allauth's
    // own pages, which link there, lead to the one sign-up form there is.
    //
    // - Not for a signed-in visitor, whom the server's redirect sends home
    //   without the fragment: a link that carries it anyway opens nothing.
    //   Nor over a screen the visitor opened while this waited.
    // - The fragment is dropped once the form has arrived, so a reload or
    //   Back does not open it again. A request that fails closes the
    //   dialog, rather than leave it open and empty, and leaves the
    //   fragment for a reload to try again.
    var signupOpened = false;
    function openSignupFromFragment() {
        if (signupOpened || window.location.hash !== '#signup') return;
        var authModal = document.getElementById('authModal');
        if (!authModal || authModal.dataset.signedIn === 'true' || authModal.open) return;
        if (typeof htmx === 'undefined') return;
        signupOpened = true;
        document.body.addEventListener('htmx:afterRequest', function settle(e) {
            if (!e.detail.target || e.detail.target.id !== 'auth-modal-content') return;
            document.body.removeEventListener('htmx:afterRequest', settle);
            if (!e.detail.successful) {
                if (authModal.open) authModal.close();
                return;
            }
            if (window.location.hash !== '#signup') return;
            window.history.replaceState(
                window.history.state, '', window.location.pathname + window.location.search
            );
        });
        openAuthModal(SIGNUP_SCREEN);
    }
    // Once htmx has started. This script is injected from an idle callback,
    // which can come before htmx, a deferred script, has run, or between
    // its running and its start: htmx reads its config and the page on
    // DOMContentLoaded. So after that event's listeners, if it is still to
    // come (the timeout lets htmx's own go first, whichever registered
    // first), and on `load` if it has gone by; the opener runs once.
    if (document.readyState === 'complete') {
        openSignupFromFragment();
    } else {
        document.addEventListener('DOMContentLoaded', function() {
            setTimeout(openSignupFromFragment, 0);
        }, { once: true });
        window.addEventListener('load', openSignupFromFragment, { once: true });
    }

    // Ensure HTMX processes content after swaps into auth modal
    document.body.addEventListener('htmx:afterSwap', function(e) {
        if (e.detail.target.id === 'auth-modal-content') {
            htmx.process(e.detail.target);
        }
    });

    // Contact modal trigger - re-query elements inside handler for robustness
    document.addEventListener('click', function(e) {
        var trigger = e.target.closest('.contact-modal-trigger');
        if (trigger) {
            var contactModal = document.getElementById('contactModal');
            if (!contactModal) return;

            e.preventDefault();

            // Pre-fill form fields from data attributes
            var category = trigger.dataset.category;
            var message = trigger.dataset.message;

            if (category) {
                var categorySelect = document.getElementById('id_category');
                if (categorySelect) categorySelect.value = category;
            }
            if (message) {
                var messageField = document.getElementById('id_message');
                if (messageField) messageField.value = message;
            }

            contactModal.showModal();
        }

        // Handle close button
        if (e.target.closest('.contact-modal-close')) {
            var contactModal = document.getElementById('contactModal');
            if (contactModal) contactModal.close();
        }
    });

    // Auto-open the contact modal (only if it exists at init)
    var contactModal = document.getElementById('contactModal');

    if (contactModal) {
        // Auto-open if hash is #contact
        if (window.location.hash === '#contact') {
            setTimeout(function() {
                contactModal.showModal();
                // Without the #contact, and with the query the reader came
                // with: this dropped it, and /?genres=1#contact lost its filter
                history.replaceState(
                    history.state, '', window.location.pathname + window.location.search
                );
            }, 100);
        }
    }
})();
