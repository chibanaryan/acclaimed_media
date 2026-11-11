/**
 * `announce` and `announceResultCount` in games/static/games/js/utils-base.js,
 * for core/tests/test_announce_js.py: what ends up in the page's one live
 * region (#live-announcer) after a list's count is rendered by the server.
 *
 *   node core/tests/js/announce.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..', '..', '..');
const noop = () => {};

// Just enough of a DOM: elements found by id, and by the three selectors
// announceResultCount asks for
const byId = {};
const listeners = {};
const element = (textContent, found = {}) => ({
    textContent,
    innerHTML: '',
    querySelector: selector => found[selector] || null,
});
globalThis.window = globalThis;
globalThis.document = {
    addEventListener: (name, handler) => { listeners[name] = handler; },
    getElementById: id => byId[id] || null,
};
globalThis.addEventListener = noop;
globalThis.dispatchEvent = noop;
globalThis.CustomEvent = class {};

const file = 'games/static/games/js/utils-base.js';
vm.runInThisContext(fs.readFileSync(path.join(root, file), 'utf8'), { filename: file });

const later = () => new Promise(resolve => setTimeout(resolve, 150));
const region = () => byId['live-announcer'].textContent;

(async () => {
    const out = {};

    // No region on the page (a template that is not base.html's)
    out.withoutRegion = (announce('Showing 5 of 5'), 'no throw');

    byId['live-announcer'] = element('');
    announce('  Showing\n   100 of\n 432  ');
    out.beforeTheTimer = region();
    await later();
    out.said = region();

    // The same words again: emptied, then said again
    announce('Showing 100 of 432');
    out.emptiedForARepeat = region();
    await later();
    out.repeated = region();

    // A burst says its last
    announce('Showing 100 of 900');
    announce('Showing 100 of 50');
    await later();
    out.burst = region();

    announce('');
    await later();
    out.nothingToSay = region();

    // A rankings page: both wordings in the list, the desktop one said
    const rankings = element('', {
        '[data-result-count="desktop"]': element('Showing 100 of 1,400'),
        '[data-result-count]': element('100 of 1,400'),
    });
    announceResultCount(rankings);
    await later();
    out.rankings = region();

    // An entity list: its heading
    announceResultCount(element('', { '#results-count': element('\n  Showing 25 of 60 artists\n') }));
    await later();
    out.entityList = region();

    // A container with no count (a tracking button, the sign-in modal)
    announce('kept');
    await later();
    announceResultCount(element('', {}));
    announceResultCount(null);
    await later();
    out.noCount = region();

    // The games rankings' server render goes through updateDomElements
    byId['game-results-container'] = element('', {
        '[data-result-count="desktop"]': element('Showing 100 of 77'),
    });
    updateDomElements({ 'game-results-container': '<div>rows</div>', missing: '<p></p>' });
    await later();
    out.afterUpdateDomElements = {
        html: byId['game-results-container'].innerHTML,
        said: region(),
    };

    // htmx swaps: one that brought a count, and a Load More's out-of-band
    // number inside an entity list's heading
    listeners['htmx:afterSettle']({
        detail: { target: element('', { '#results-count': element('3 publications (9 lists)') }) },
    });
    await later();
    out.afterSettle = region();

    const heading = element('Showing 50 of 60 artists');
    listeners['htmx:oobAfterSwap']({
        target: { id: 'loaded-count', closest: selector => (selector === '#results-count' ? heading : null) },
    });
    await later();
    out.outOfBandCount = region();

    // The rankings' own count sits in a role="status" that stayed put
    announce('kept');
    await later();
    listeners['htmx:oobAfterSwap']({ target: { id: 'loaded-count', closest: () => null } });
    listeners['htmx:oobAfterSwap']({ target: { id: 'load-more-container', closest: () => heading } });
    await later();
    out.outOfBandElsewhere = region();

    // A count becomes a live region once it is on the page, not before
    const roles = [];
    const counts = [0, 1].map(index => ({ setAttribute: (name, value) => roles.push([index, name, value]) }));
    const list = element('', { '[data-result-count="desktop"]': element('Showing 9 of 9') });
    list.querySelectorAll = selector => (selector === '[data-result-count]' ? counts : []);
    announceResultCount(list);
    await later();
    out.madeLive = { roles, said: region() };
    markResultCountsLive(null);
    markResultCountsLive(element('', {}));

    process.stdout.write(JSON.stringify(out));
})();
