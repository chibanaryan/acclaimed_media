/**
 * Runs the client-side filter engines under Node, for the parity tests in
 * core/tests/test_filter_parity.py.
 *
 *   node core/tests/js/filter_parity.js input.json
 *
 * input.json: {"music": {"payload": ..., "queries": ["q=x&sort=year", ...]},
 *              "games": {"payload": ..., "queries": [...]}}
 * Prints {"music": {query: [ids in order]}, "games": {...}} to stdout.
 * With "credits": true under "music", it also prints "musicCredits": {album
 * id: the renderer's credit-line HTML}, to compare with `artist_links`.
 *
 * The real engine files are loaded, not copies, and so is the real mapping
 * from the page's state to the engine's filters: music's `readFilters`
 * (given the query string where the page gives it a FormData) and games'
 * `getFiltersFromURL` plus `ClientSideFiltering.applyFilters`, the path
 * jump-to-rank takes. Only the browser around them is stubbed.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..', '..', '..');
const input = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));

const noop = () => {};
globalThis.window = globalThis;
globalThis.document = {
    readyState: 'loading',  // modules defer their DOM wiring, which never runs
    addEventListener: noop,
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
    body: { addEventListener: noop },
};
globalThis.localStorage = { getItem: () => null, setItem: noop, removeItem: noop };
globalThis.sessionStorage = globalThis.localStorage;
globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } };
globalThis.dispatchEvent = noop;
globalThis.addEventListener = noop;
globalThis.matchMedia = () => ({ matches: true, addEventListener: noop });
globalThis.location = { search: '', pathname: '/' };
// The page's FormData wraps a form; readFilters only calls .get(name)
globalThis.FormData = class { constructor(params) { this.params = params; } get(name) { return this.params.get(name); } };
// No landing-page paths here: the queries are plain query strings
globalThis.seoPathSearch = () => '';

function load(relative) {
    vm.runInThisContext(fs.readFileSync(path.join(root, relative), 'utf8'), { filename: relative });
}

const output = {};

if (input.music) {
    load('music/static/music/js/album-filter.js');
    load('music/static/music/js/album-client-filtering.js');
    const engine = new AlbumFilterEngine(input.music.payload);
    const readFilters = AlbumClientSideFiltering.prototype.readFilters;
    output.music = {};
    for (const query of input.music.queries) {
        const filters = readFilters.call(null, new URLSearchParams(query));
        output.music[query] = engine.apply(filters).albums.map(album => album.id);
    }
    if (input.music.credits) {
        load('core/static/core/js/base-renderer.js');
        load('music/static/music/js/album-list-renderer.js');
        // What `div.textContent = text; div.innerHTML` gives in a browser.
        const escaper = {
            _escapeHtml: text => String(text || '')
                .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
        };
        const creditHtml = AlbumListRenderer.prototype._artistCreditHtml;
        output.musicCredits = {};
        for (const album of input.music.payload.albums) {
            output.musicCredits[album.id] = creditHtml.call(
                escaper, engine.expandAlbum(album)
            );
        }
    }
}

if (input.games) {
    load('games/static/games/js/utils-base.js');
    load('games/static/games/js/client-filter.js');
    load('games/static/games/js/client-filtering.js');
    load('games/static/games/js/utils-loadmore.js');
    const engine = new GameFilterEngine(input.games.payload);
    const csf = { isInitialized: true, engine, renderer: null };
    output.games = {};
    for (const query of input.games.queries) {
        globalThis.location = { search: '?' + query, pathname: '/' };
        const filters = getFiltersFromURL();
        const result = ClientSideFiltering.prototype.applyFilters.call(csf, filters);
        output.games[query] = result.games.map(game => game.id);
    }
}

process.stdout.write(JSON.stringify(output));
