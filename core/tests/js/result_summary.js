/**
 * The renderers' count line, for core/tests/test_result_summary_js.py,
 * which compares it with what _media_list_controls.html renders.
 *
 *   node core/tests/js/result_summary.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..', '..', '..');
globalThis.window = globalThis;
for (const file of [
    'core/static/core/js/base-renderer.js',
    'games/static/games/js/game-list-renderer.js',
    'music/static/music/js/album-list-renderer.js',
]) {
    vm.runInThisContext(fs.readFileSync(path.join(root, file), 'utf8'), { filename: file });
}

const lines = Renderer => {
    const proto = Renderer.prototype;
    const say = (loaded, total, options) => proto.getResultSummaryHtml.call(proto, loaded, total, options);
    return {
        empty: say(0, 0, {}),
        emptyCompact: say(0, 0, { compact: true }),
        some: say(3, 10, {}),
    };
};
process.stdout.write(JSON.stringify({
    games: lines(window.GameListRenderer),
    music: lines(window.AlbumListRenderer),
}));
