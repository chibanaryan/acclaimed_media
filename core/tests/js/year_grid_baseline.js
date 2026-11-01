/**
 * Runs the year grid under Node for core/tests/test_year_grid_baseline.py.
 *
 *   node core/tests/js/year_grid_baseline.js
 *
 * Builds the grid as a page loaded with a narrow filter would - its
 * `year-counts-data` the filter's counts - once with the page's whole-corpus
 * `year-baseline-counts-data` and once without, and prints the colour scale
 * each ends up with, plus the opacity of a count above a stale scale. Also
 * reports which neighbours a tile sees around a year missing from the counts.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..', '..', '..');
const noop = () => {};
const documentListeners = {};
let elements = {};
globalThis.window = globalThis;
globalThis.document = {
    addEventListener: (type, handler) => {
        (documentListeners[type] = documentListeners[type] || []).push(handler);
    },
    getElementById: id => (id in elements ? { textContent: JSON.stringify(elements[id]) } : null),
};
globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init && init.detail; } };
globalThis.addEventListener = noop;
globalThis.removeEventListener = noop;
globalThis.dispatchEvent = noop;

const factories = {};
globalThis.Alpine = { data: (name, factory) => { factories[name] = factory; } };
vm.runInThisContext(
    fs.readFileSync(path.join(root, 'core/static/core/js/filter-subcomponents.js'), 'utf8')
);
documentListeners['alpine:init'].forEach(handler => handler());

const filtered = [{ year: 1970, count: 1 }, { year: 1971, count: 0 }, { year: 1972, count: 0 }];
const corpus = [{ year: 1970, count: 20 }, { year: 1971, count: 12 }, { year: 1972, count: 3 }];

function build(withBaseline) {
    elements = { 'year-counts-data': filtered };
    if (withBaseline) elements['year-baseline-counts-data'] = corpus;
    const grid = factories.yearGridComponent({ filters: {}, minYear: 1970, maxYear: 1972 });
    grid.init();
    return {
        maxCount: grid.maxCount,
        originalMaxCount: grid.originalMaxCount,
        current: grid.yearCounts.map(y => y.count),
        cells: grid.decades[0].cells.filter(c => c.year).map(c => c.year),
    };
}

const stale = factories.yearGridComponent({ filters: {}, minYear: 1970, maxYear: 1972 });
stale.maxCount = 1;

// 1971 has no count, so its cell is filled in; 1983 on have no cell at all.
elements = {
    'year-counts-data': [1960, 1961, 1962, 1970, 1972, 1980, 1981, 1982].map(year => ({ year, count: 1 })),
};
const gappy = factories.yearGridComponent({ filters: { start: 1960, end: 1989 }, minYear: 1950, maxYear: 1990 });
gappy.init();
// A range can name decades the grid has no row for: filters come from the URL.
const unclamped = factories.yearGridComponent({ filters: { start: 1960, end: 1999 }, minYear: 1950, maxYear: 2000 });
unclamped.init();
// A drag from the first decade's label to the last's ends at its 9, past the
// last year. A narrower drag keeps its own ends.
const filtersOf = { start: 1960, end: 1982 };
const overshoot = factories.yearGridComponent({ filters: filtersOf, minYear: 1960, maxYear: 1982, requestFilterUpdate: noop });
overshoot.init();
// A link from an old drag, which ran past the last year: filters stay as read.
const oldLink = { start: 1960, end: 1989 };
elements = { 'year-counts-data': [1960, 1961, 1962, 1970, 1972, 1980, 1981, 1982].map(year => ({ year, count: 1 })) };
const oldLinkGrid = factories.yearGridComponent({ filters: oldLink, minYear: 1960, maxYear: 1982 });
oldLinkGrid.init();

// Press, release, click, as the browser sends them.
const gesture = (grid, kind, value, shiftKey) => {
    const event = { preventDefault: noop, shiftKey };
    if (kind === 'decade') grid.startDragDecade(value, event); else grid.startDrag(value, event);
    grid.endDrag();
    if (kind === 'decade') grid.pickRange(event, value, value + 9); else grid.pickRange(event, value, value);
};
const roomyFilters = { start: 1950, end: 1999 };
const roomy = factories.yearGridComponent({ filters: roomyFilters, minYear: 1950, maxYear: 1999, requestFilterUpdate: noop });
roomy.init();
const range = () => [roomyFilters.start, roomyFilters.end];
const clear = () => { roomyFilters.start = 1950; roomyFilters.end = 1999; };
const shiftFrom = (kind, first, shiftKind, second) => {
    clear();
    gesture(roomy, kind, first, false);
    gesture(roomy, shiftKind, second, true);
    return range();
};
const dragThenShift = (from, to, kind, value) => {
    clear();
    roomy.startDrag(from, { preventDefault: noop });
    roomy.updateDrag(to);
    roomy.endDrag();
    gesture(roomy, kind, value, true);
    return range();
};
const labelReleasedOffItsTile = () => {
    clear();
    gesture(roomy, 'year', 1990, false);
    // Pressed on the 1970s label, released on 1979: no click lands on a tile
    roomy.startDragDecade(1970, { preventDefault: noop });
    roomy.endDrag();
    gesture(roomy, 'year', 1985, true);
    return range();
};
// Loaded from a link, or set by a saved filter: nothing the grid picked itself.
const shiftFromARangeItDidNotPick = () => {
    roomyFilters.start = 1970;
    roomyFilters.end = 1979;
    gesture(roomy, 'year', 1985, true);
    return range();
};
// Shift held, released on another tile: no click event comes at all.
const shiftDragWithNoClick = () => {
    clear();
    gesture(roomy, 'year', 1970, false);
    roomy.startDrag(1980, { preventDefault: noop, shiftKey: true });
    roomy.updateDrag(1981);
    roomy.endDrag();
    return range();
};
// While Shift is pressed, what shows is the range it will make.
const whileShiftIsDown = () => {
    clear();
    gesture(roomy, 'decade', 1970, false);
    roomy.startDrag(1985, { preventDefault: noop, shiftKey: true });
    const shown = {
        stillLit: roomy.isInRange(1975),
        labelStillLit: roomy.isDecadeSelected(1970),
        pressedLit: roomy.isInRange(1985),
    };
    roomy.cancelDrag();
    return shown;
};
const secondClickClears = () => {
    clear();
    gesture(roomy, 'year', 1975, false);
    gesture(roomy, 'year', 1975, false);
    return range();
};
// Assistive tech can send a click with no press before it.
const clickAlone = () => {
    clear();
    roomy.pressApplied = false;
    roomy.pickRange({}, 1970, 1979);
    const picked = range();
    roomy.pickRange({}, 1970, 1979);
    return { picked, again: range() };
};
// Chromium's accessibility action can send press and release too, with detail 0.
const fullGestureFromAssistiveTech = () => {
    clear();
    gesture(roomy, 'year', 1975, false);
    return range();
};
const shiftPressOnALabel = () => {
    clear();
    roomyFilters.start = 1962;
    roomyFilters.end = 1969;
    roomy.startDragDecade(1970, { preventDefault: noop, shiftKey: true });
    const lit = roomy.isDecadeSelected(1970);
    roomy.cancelDrag();
    return lit;
};
// A press dragged out of the grid: its tile must not read as clicked later.
const pressThenLeave = () => {
    clear();
    gesture(roomy, 'year', 1975, false);
    roomy.startDrag(1975, { preventDefault: noop });
    roomy.cancelDrag();
    roomy.endDrag();
    roomy.pickRange({}, 1975, 1975);
    return range();
};
// A label shows while dragging what it will show after: lit only for a range
// that covers its whole decade, so a label dragged onto a year goes dark.
const labelDraggedOntoAYear = () => {
    clear();
    roomy.startDragDecade(1970, { preventDefault: noop });
    const pressed = roomy.isDecadeSelected(1970);
    roomy.updateDrag(1985);
    const dragged = roomy.isDecadeSelected(1970);
    roomy.updateDragDecade(1980);
    const acrossDecades = [roomy.isDecadeSelected(1970), roomy.isDecadeSelected(1980)];
    roomy.cancelDrag();
    return { pressed, dragged, acrossDecades };
};
const dragAcross = (fromDecade, toDecade) => {
    overshoot.startDragDecade(fromDecade, { preventDefault: noop });
    overshoot.updateDragDecade(toDecade);
    overshoot.endDrag();
    return [filtersOf.start, filtersOf.end];
};

// What the timer after a release does, which needs real turns of the loop.
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const afterTheRelease = async () => {
    // Released on another tile: no click, so the press must not linger
    clear();
    roomy.startDrag(1975, { preventDefault: noop });
    roomy.updateDrag(1978);
    roomy.endDrag();
    await tick();
    roomy.pickRange({}, 1980, 1980);
    const bareClickPicks = range();
    // A second press beats the first release's timer
    clear();
    roomy.startDrag(1975, { preventDefault: noop });
    roomy.endDrag();
    roomy.startDrag(1975, { preventDefault: noop });
    await tick();
    const stillPressed = roomy.pressApplied;
    roomy.endDrag();
    const dragEnded = !roomy.isDragging;
    // A right-click on a tile selects nothing and starts no drag
    clear();
    roomy.startDrag(1975, { preventDefault: noop, button: 2 });
    const rightClickDrags = roomy.isDragging;
    roomy.startDrag(1975, { preventDefault: noop, ctrlKey: true });
    return {
        bareClickPicks,
        stillPressed,
        dragEnded,
        rightClickDrags,
        controlClickDrags: roomy.isDragging,
    };
};

afterTheRelease().then(timing => process.stdout.write(JSON.stringify({
    timing,
    neighbours: {
        rightOntoFilledCell: gappy.hasSelectedRight(1970),
        belowOntoFilledCell: gappy.hasSelectedBelow(1981),
        aboveOntoFilledCell: gappy.hasSelectedAbove(1961),
        rightOntoNoCell: gappy.hasSelectedRight(1982),
        decadeBelowRow: unclamped.decadeHasSelectedBelow(1970),
        decadeAboveNoRow: unclamped.decadeHasSelectedAbove(1980),
        decadeBelowNoRow: unclamped.decadeHasSelectedBelow(1960),
        firstColumnLeftIsTheLabel: unclamped.hasSelectedLeft(1970),
    },
    decadeThenLowerDecade: shiftFrom('decade', 1970, 'decade', 1960),
    decadeThenYearInside: shiftFrom('decade', 1970, 'year', 1975),
    decadeThenHigherYear: shiftFrom('decade', 1960, 'year', 1975),
    yearThenLowerYear: shiftFrom('year', 1975, 'year', 1962),
    decadeThenLowerYear: shiftFrom('decade', 1970, 'year', 1962),
    oldLinkLightsNothing: !oldLinkGrid.isInRange(1970) && !oldLinkGrid.isDecadeSelected(1970),
    shiftAfterDrag: dragThenShift(1985, 1992, 'year', 1961),
    shiftOverlappingADrag: dragThenShift(1965, 1985, 'decade', 1960),
    labelReleasedOffItsTile: labelReleasedOffItsTile(),
    shiftFromARangeItDidNotPick: shiftFromARangeItDidNotPick(),
    shiftDragWithNoClick: shiftDragWithNoClick(),
    whileShiftIsDown: whileShiftIsDown(),
    secondClickClears: secondClickClears(),
    labelDraggedOntoAYear: labelDraggedOntoAYear(),
    clickAlone: clickAlone(),
    fullGestureFromAssistiveTech: fullGestureFromAssistiveTech(),
    shiftPressOnALabel: shiftPressOnALabel(),
    pressThenLeave: pressThenLeave(),
    wholeDrag: dragAcross(1960, 1980),
    partialDrag: dragAcross(1970, 1980),
    rowOrder: gappy.decades.map(decade => decade.start),
    withBaseline: build(true),
    withoutBaseline: build(false),
    opacityAboveScale: stale.getOpacity(20),
})));
