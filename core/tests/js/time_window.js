/**
 * Runs the client's time window, its tab-title form and the facets' join for
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
globalThis.window = globalThis;
globalThis.document = { addEventListener: noop, getElementById: () => null };
globalThis.addEventListener = noop;
globalThis.dispatchEvent = noop;
globalThis.CustomEvent = class {};
const file = 'games/static/games/js/utils-base.js';
vm.runInThisContext(fs.readFileSync(path.join(root, file), 'utf8'), { filename: file });

const cases = JSON.parse(process.argv[2]);
window._seoUrlData = { genres: { 5: 'rock' } };

process.stdout.write(JSON.stringify({
    windows: cases.map(([start, end, min, max]) => buildTimeWindow(start, end, min, max)),
    shortWindows: cases.map(([start, end, min, max]) => shortTimeWindow(start, end, min, max)),
    shortTitle: shortTitle(['Rock', '', '1990s', null, 'Heard']),
    cleanUrlPastTheLastYear: seoCleanUrl(new URLSearchParams('genres=5&start=1971&end=2029'), 1971, 2026),
    cleanUrlOfARealRange: seoCleanUrl(new URLSearchParams('genres=5&start=1980&end=2029'), 1971, 2026),
}));
