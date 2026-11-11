/**
 * The two search boxes' requests, out of order, for
 * core/tests/test_search_requests_js.py: games' createUnifiedSearchData
 * (games/static/games/js/utils-base.js) and music's createMediaSearchData
 * (core/static/core/js/media-search.js), on the real files.
 *
 * `fetch` here answers when the harness says so, and rejects as a browser's
 * does when its signal is aborted - or, for the `deaf` runs, ignores the
 * signal and answers late anyway, which is what a response already being
 * read amounts to.
 *
 *   node core/tests/js/search_requests.js
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
console.error = noop;

for (const file of [
    'games/static/games/js/utils-base.js',
    'core/static/core/js/media-search.js',
]) {
    vm.runInThisContext(fs.readFileSync(path.join(root, file), 'utf8'), { filename: file });
}

let pending = [];
let deaf = false;
globalThis.fetch = (url, options) => new Promise((resolve, reject) => {
    const signal = (options || {}).signal;
    const query = new URL(url, 'https://example.test').searchParams.get('q');
    pending.push({
        query,
        hadSignal: Boolean(signal),
        answer: body => resolve({ ok: true, status: 200, json: async () => body }),
        fail: () => resolve({ ok: false, status: 500, json: async () => ({}) }),
    });
    if (signal && !deaf) {
        signal.addEventListener('abort', () => {
            const error = new Error('The operation was aborted.');
            error.name = 'AbortError';
            reject(error);
        });
    }
});

// Long enough for every `await` in loadResults to run its continuation
const settle = () => new Promise(resolve => setTimeout(resolve, 0));
const request = query => pending.find(entry => entry.query === query);

const boxes = {
    games: {
        make: () => createUnifiedSearchData('/api/unified-search/', 3, 5),
        body: name => ({ games: [{ name }], developers: [], series: [] }),
        names: box => box.games.map(game => game.name),
    },
    music: {
        make: () => createMediaSearchData('/api/unified-search/', { artists: 3, albums: 5 }),
        body: name => ({ albums: [{ name }], artists: [] }),
        names: box => box.results.albums.map(album => album.name),
    },
};

async function run({ make, body, names }) {
    const out = {};
    const state = box => ({ names: names(box), loading: box.loading });
    const start = () => {
        pending = [];
        return make();
    };

    for (const mode of ['aborting', 'deaf']) {
        deaf = mode === 'deaf';

        // "be" is slow; "beatles" is asked for after it and answered first
        let box = start();
        box.q = 'be';
        const first = box.loadResults();
        box.q = 'beatles';
        const second = box.loadResults();
        await settle();
        const whileNewerIsOut = state(box);
        request('beatles').answer(body('for beatles'));
        await second;
        request('be').answer(body('for be'));
        await first;
        await settle();
        out[mode + 'Overtaken'] = {
            sentSignals: pending.every(entry => entry.hadSignal),
            whileNewerIsOut,
            after: state(box),
        };

        // The box is emptied while a request is out
        box = start();
        box.q = 'be';
        const asked = box.loadResults();
        box.q = 'b';
        await box.loadResults();
        request('be').answer(body('for be'));
        await asked;
        await settle();
        out[mode + 'Cleared'] = state(box);

        // reset() (the box's clear button) while one is out
        box = start();
        box.q = 'be';
        const beforeReset = box.loadResults();
        box.reset();
        request('be').answer(body('for be'));
        await beforeReset;
        await settle();
        out[mode + 'Reset'] = state(box);
    }
    deaf = false;

    // Nothing in the way: the answer is shown, and a failure shows nothing
    let box = start();
    box.q = 'beatles';
    let asked = box.loadResults();
    const loadingWhileOut = box.loading;
    request('beatles').answer(body('for beatles'));
    await asked;
    out.alone = { loadingWhileOut, after: state(box) };

    box = start();
    box.q = 'beatles';
    asked = box.loadResults();
    request('beatles').fail();
    await asked;
    out.failed = state(box);
    // Said as a failure, not as no results; the next keystroke starts over
    out.failedFlag = box.failed;
    box.q = 'beatle';
    asked = box.loadResults();
    request('beatle').answer(body('for beatle'));
    await asked;
    out.failedThenAnswered = box.failed;

    // Two boxes on one page (sidebar and mobile bar) do not abort each other
    const one = start();
    const other = make();
    one.q = 'abbey';
    other.q = 'revolver';
    const askedOne = one.loadResults();
    const askedOther = other.loadResults();
    request('abbey').answer(body('for abbey'));
    request('revolver').answer(body('for revolver'));
    await Promise.all([askedOne, askedOther]);
    out.twoBoxes = [state(one), state(other)];

    return out;
}

(async () => {
    const output = {};
    for (const [name, box] of Object.entries(boxes)) {
        output[name] = await run(box);
    }
    process.stdout.write(JSON.stringify(output));
})();
