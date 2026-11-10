/**
 * Runs the renderers' `_escapeHtml` over the strings given, for
 * core/tests/test_escape_html.py, which compares it with Django's `escape`.
 *
 *   node core/tests/js/escape_html.js '["Bonnie \"Prince\" Billy"]'
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..', '..', '..');
globalThis.window = globalThis;
// No `document`: the escaper must not need a DOM to do its job
const file = 'core/static/core/js/base-renderer.js';
vm.runInThisContext(fs.readFileSync(path.join(root, file), 'utf8'), { filename: file });

const escape = window.BaseMediaListRenderer.prototype._escapeHtml;
process.stdout.write(JSON.stringify(JSON.parse(process.argv[2]).map(text => escape(text))));
