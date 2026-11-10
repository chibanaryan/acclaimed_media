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

    // Auth modal trigger - re-query elements inside handler for robustness
    document.addEventListener('click', function(e) {
        var trigger = e.target.closest('.auth-modal-trigger');
        if (trigger) {
            var authModal = document.getElementById('authModal');
            if (!authModal) return;

            e.preventDefault();
            // Check for specific screen to load
            var screen = trigger.dataset.authScreen;
            var url = '/auth/modal/login/';
            if (screen === 'profile') {
                // Add cache-buster to ensure fresh data every time
                url = '/auth/modal/profile/?_=' + Date.now();
            } else if (screen === 'signup') {
                url = '/auth/modal/signup/?direct=1';
            }
            htmx.ajax('GET', url, {target: '#auth-modal-content', swap: 'innerHTML'});
            authModal.showModal();
        }
    });

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
