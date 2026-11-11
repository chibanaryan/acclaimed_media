/**
 * The search boxes' keyboard behaviour (`searchComboboxState` in
 * games/static/games/js/utils-base.js), through both search components, for
 * core/tests/test_search_combobox.py. The listbox is a stand-in: an id and
 * the options a query for `[role="option"]` would find.
 *
 *   node core/tests/js/search_combobox.js
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
globalThis.fetch = () => new Promise(noop);

for (const file of [
    'games/static/games/js/utils-base.js',
    'core/static/core/js/media-search.js',
]) {
    vm.runInThisContext(fs.readFileSync(path.join(root, file), 'utf8'), { filename: file });
}

function option(name, log) {
    const attributes = {};
    return {
        name,
        id: '',
        getAttribute: key => (key in attributes ? attributes[key] : null),
        setAttribute: (key, value) => { attributes[key] = value; },
        removeAttribute: key => { delete attributes[key]; },
        scrollIntoView: where => log.push(['scrolled', name, where.block]),
        click: () => log.push(['clicked', name]),
    };
}

function withListbox(box, names, log) {
    const options = names.map(name => option(name, log));
    box.$refs = {
        listbox: {
            id: 'results',
            querySelectorAll: selector => (selector === '[role="option"]' ? options : []),
        },
    };
    return options;
}

const selected = options => options.filter(o => o.getAttribute('aria-selected') === 'true').map(o => o.name);

const makers = {
    games: () => createUnifiedSearchData('/api/unified-search/', 3, 5),
    music: () => createMediaSearchData('/api/unified-search/', { artists: 3, albums: 5 }),
};

const out = {};
for (const [site, make] of Object.entries(makers)) {
    const log = [];
    const result = {};
    let box = make();
    result.startsWithNone = box.activeOption;

    // No listbox at all (the harness of the request tests, a page mid-load)
    box.moveOption(1);
    result.noListbox = { active: box.activeOption, entered: box.activateOption({}) };

    // A listbox with nothing in it
    withListbox(box, [], log);
    box.moveOption(1);
    result.noOptions = box.activeOption;

    // Down from the field, down again, and round to the top
    let options = withListbox(box, ['first', 'second', 'third'], log);
    const steps = [];
    for (const step of [1, 1, 1, 1, -1, -1]) {
        box.moveOption(step);
        steps.push([box.activeOption, selected(options).join()]);
    }
    result.steps = steps;
    result.ids = options.map(o => o.id);
    result.unselected = options.map(o => o.getAttribute('aria-selected'));

    // Up from the field starts at the bottom
    box = make();
    options = withListbox(box, ['first', 'second', 'third'], log);
    box.moveOption(-1);
    result.upFirst = selected(options).join();

    // Enter follows the active option, and says so
    let prevented = 0;
    result.entered = box.activateOption({ preventDefault: () => { prevented += 1; } });
    result.prevented = prevented;
    result.clicked = log.filter(entry => entry[0] === 'clicked').map(entry => entry[1]);

    // With none active, Enter is left to the caller: the full search
    box.clearActiveOption();
    result.cleared = { active: box.activeOption, selected: selected(options) };
    result.enteredWithNone = box.activateOption({ preventDefault: () => { prevented += 1; } });
    result.preventedAfter = prevented;

    // A new query, or the clear button, forgets the active option
    box.moveOption(1);
    box.q = 'beatles';
    box.loadResults();
    result.afterNewQuery = { active: box.activeOption, selected: selected(options) };
    box.moveOption(1);
    box.reset();
    result.afterReset = { active: box.activeOption, selected: selected(options) };

    // A keyed loop reuses elements: ids follow the positions as they are now
    options = withListbox(box, ['kept', 'new'], log);
    options[0].id = 'results-option-4';
    box.moveOption(1);
    result.renumbered = options.map(o => o.id);

    result.scrolledNearest = log.filter(entry => entry[0] === 'scrolled').every(entry => entry[2] === 'nearest');
    out[site] = result;
}
process.stdout.write(JSON.stringify(out));
