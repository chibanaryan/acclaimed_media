/**
 * Small behaviours of games/static/games/js/utils-base.js that only show up
 * when the browser refuses something, for core/tests/test_utils_base_js.py:
 * storage that throws on every access, and a fetch answered with an error.
 *
 *   node core/tests/js/utils_base.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..', '..', '..');
const noop = () => {};
globalThis.window = globalThis;
globalThis.document = { addEventListener: noop, getElementById: () => null };
globalThis.addEventListener = noop;
globalThis.dispatchEvent = noop;
globalThis.CustomEvent = class {};

// As Chrome with "Block all cookies": the property itself throws
const refuse = () => { throw new Error('SecurityError'); };
const kept = {};
const working = {
    getItem: key => (key in kept ? kept[key] : null),
    setItem: (key, value) => { kept[key] = String(value); },
    removeItem: key => { delete kept[key]; },
};
let storage = refuse;
Object.defineProperty(globalThis, 'localStorage', { get: () => storage(), configurable: true });
Object.defineProperty(globalThis, 'sessionStorage', { get: () => storage(), configurable: true });

const file = 'games/static/games/js/utils-base.js';
vm.runInThisContext(fs.readFileSync(path.join(root, file), 'utf8'), { filename: file });

(async () => {
    const refused = {
        read: readStoredPreference('yearExpanded'),
        readSession: readStoredPreference('gameListScrollPos', true),
        json: readStoredJson('mobileFilterExpanded_time', true),
        stored: (storePreference('yearExpanded', 'false'), 'no throw'),
        removed: (removeStoredPreference('yearExpanded'), 'no throw'),
    };

    storage = () => working;
    storePreference('yearExpanded', false);
    storePreference('expandedCategories', JSON.stringify({ 3: true }));
    kept.broken = '{not json';
    const allowed = {
        read: readStoredPreference('yearExpanded'),
        json: readStoredJson('expandedCategories', {}),
        missingJson: readStoredJson('nothing', true),
        brokenJson: readStoredJson('broken', 'fallback'),
        noKey: readStoredPreference(''),
    };
    removeStoredPreference('yearExpanded');
    allowed.afterRemove = readStoredPreference('yearExpanded');

    const answers = {};
    for (const [name, response] of Object.entries({
        ok: { ok: true, status: 200, text: async () => '<p>rows</p>' },
        error: { ok: false, status: 500, text: async () => '<h1>Server Error</h1>' },
    })) {
        globalThis.fetch = async () => response;
        try {
            answers[name] = { html: await fetchHtml('/?q=x') };
        } catch (error) {
            answers[name] = { error: error.message };
        }
    }
    const scrolls = {};
    for (const [name, matchMedia] of Object.entries({
        reduced: query => ({ matches: query === '(prefers-reduced-motion: reduce)' }),
        unreduced: () => ({ matches: false }),
        unknown: undefined,
    })) {
        globalThis.matchMedia = matchMedia;
        scrolls[name] = scrollBehavior();
    }
    process.stdout.write(JSON.stringify({ refused, allowed, answers, scrolls }));
})();
