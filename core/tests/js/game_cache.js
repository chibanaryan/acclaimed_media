/**
 * GameDataCache when IndexedDB fails, for core/tests/test_game_cache_js.py.
 * Each case gives the real file a fake `indexedDB` and a fake `fetch`, and
 * records what `getData` answered.
 *
 *   node core/tests/js/game_cache.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..', '..', '..');
globalThis.window = globalThis;
console.warn = () => {};
console.error = () => {};
const file = 'games/static/games/js/game-cache.js';
vm.runInThisContext(fs.readFileSync(path.join(root, file), 'utf8'), { filename: file });

const PAYLOAD = { version: 'v1', data: { games: [1, 2, 3] } };
globalThis.fetch = async () => ({ ok: true, json: async () => PAYLOAD });
window.gameDataVersion = 'v1';

// A request that fails asynchronously, as IndexedDB's do
function failingRequest() {
    const request = {};
    setTimeout(() => { request.error = new Error('lost'); request.onerror && request.onerror(); }, 0);
    return request;
}

function fakeDb({ transactionThrows = false } = {}) {
    return {
        objectStoreNames: { contains: () => true },
        transaction() {
            if (transactionThrows) throw new Error('connection to IndexedDB lost');
            return { objectStore: () => ({ get: failingRequest, put: failingRequest, delete: failingRequest }) };
        },
        close() { this.closed = true; },
    };
}

function openingWith(db) {
    return {
        open() {
            const request = {};
            setTimeout(() => { request.result = db; request.onsuccess && request.onsuccess(); }, 0);
            return request;
        },
    };
}

async function attempt(name, indexedDB) {
    globalThis.indexedDB = indexedDB;
    const cache = new window.GameDataCache();
    try {
        const data = await cache.getData();
        const cleared = await cache.clearCache().then(() => 'no throw', e => String(e));
        return [name, { data, cleared }];
    } catch (e) {
        return [name, { error: String(e) }];
    }
}

(async () => {
    const results = Object.fromEntries(await Promise.all([
        attempt('requestFails', openingWith(fakeDb())),
        attempt('transactionThrows', openingWith(fakeDb({ transactionThrows: true }))),
        attempt('noIndexedDB', { open() { throw new Error('not allowed'); } }),
    ]));
    // A connection another tab's upgrade asks to close is closed and
    // forgotten, so the next use opens a new one
    globalThis.indexedDB = openingWith(fakeDb());
    const cache = new window.GameDataCache();
    const db = await cache._initDB();
    if (typeof db.onversionchange === 'function') db.onversionchange();
    results.versionChange = { closed: !!db.closed, forgotten: cache._db === null };
    process.stdout.write(JSON.stringify(results));
})();
