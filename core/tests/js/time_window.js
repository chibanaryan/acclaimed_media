/**
 * Runs both client copies of the heading's time window for
 * core/tests/test_time_window_parity.py, which compares them with
 * core/services/titles.py, and seoCleanUrl on a range past the last year.
 *
 *   node core/tests/js/time_window.js '[[1990, 2029, 1970, 2026]]'
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..', '..', '..');
const noop = () => {};
const listeners = {};
globalThis.window = globalThis;
globalThis.document = {
    addEventListener: (type, handler) => { (listeners[type] = listeners[type] || []).push(handler); },
    getElementById: id => ({ textContent: id === 'filters-data' ? '{}' : '[]' }),
    querySelector: () => null,
    querySelectorAll: () => [],
};
globalThis.addEventListener = noop;
globalThis.removeEventListener = noop;
globalThis.dispatchEvent = noop;
globalThis.CustomEvent = class {};
globalThis.localStorage = { getItem: () => null, setItem: noop };
const factories = {};
globalThis.Alpine = { data: (name, factory) => { factories[name] = factory; } };

for (const file of [
    'games/static/games/js/utils-base.js',
    'core/static/core/js/media-list-controls.js',
    'games/static/games/js/filter-component.js',
]) {
    vm.runInThisContext(fs.readFileSync(path.join(root, file), 'utf8'), { filename: file });
}
listeners['alpine:init'].forEach(handler => handler());

const games = factories.filterComponent({ minYear: 0, maxYear: 0 });
const cases = JSON.parse(process.argv[2]);
window._seoUrlData = { genres: { 5: 'rock' } };

process.stdout.write(JSON.stringify({
    shared: cases.map(([start, end, min, max]) => buildTimeWindow(start, end, min, max)),
    games: cases.map(([start, end, min, max]) => games._buildTimeWindow.call(
        { filters: { start, end }, minYear: min, maxYear: max }
    )),
    cleanUrlPastTheLastYear: seoCleanUrl(new URLSearchParams('genres=5&start=1971&end=2029'), 1971, 2026),
    cleanUrlOfARealRange: seoCleanUrl(new URLSearchParams('genres=5&start=1980&end=2029'), 1971, 2026),
}));
