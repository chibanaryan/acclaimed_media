/**
 * Prints the album renderer's Load More markup for each paging state given,
 * for music/tests/test_load_more_parity.py, which compares it with what
 * `_album_load_more.html` renders for the same state.
 *
 *   node core/tests/js/load_more_markup.js '[{"hasMore": false, "total": 3}]'
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..', '..', '..');
globalThis.window = globalThis;
for (const file of [
    'core/static/core/js/base-renderer.js',
    'music/static/music/js/album-list-renderer.js',
]) {
    vm.runInThisContext(fs.readFileSync(path.join(root, file), 'utf8'), { filename: file });
}

const markup = state => window.AlbumListRenderer.prototype.getLoadMoreHtml.call(
    window.AlbumListRenderer.prototype, state
);
process.stdout.write(JSON.stringify(JSON.parse(process.argv[2]).map(markup)));
