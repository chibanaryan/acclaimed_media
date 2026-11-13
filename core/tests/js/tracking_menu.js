/**
 * The tracking button's menu keys in core/static/core/js/media-tracking.js,
 * for core/tests/test_tracking_menu_js.py: the real file, driven through the
 * two document listeners it installs, over just enough of a DOM.
 *
 *   node core/tests/js/tracking_menu.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..', '..', '..');
const listeners = {};
const dispatched = [];
const frames = [];

globalThis.window = globalThis;
globalThis.document = {
    addEventListener: (name, handler, capture) => {
        listeners[name + (capture ? ':capture' : '')] = handler;
    },
    activeElement: null,
};
globalThis.dispatchEvent = event => { dispatched.push(event.type); };
globalThis.CustomEvent = class { constructor(type) { this.type = type; } };
globalThis.requestAnimationFrame = callback => { frames.push(callback); };

const file = 'core/static/core/js/media-tracking.js';
vm.runInThisContext(fs.readFileSync(path.join(root, file), 'utf8'), { filename: file });
MediaTracking.register('album', { sets: {}, event: 'album-status-changed' });

/** A wrapper with a trigger and `count` menu items, shown or not. */
function build(count, { open = true } = {}) {
    const wrapper = { shown: open, dataset: { trackingScope: 'album' } };
    const element = (name) => ({
        name,
        clicks: 0,
        focus() { document.activeElement = this; },
        click() { this.clicks += 1; },
        closest: selector => (
            selector === '.tracking-button-wrapper' ? wrapper
                : selector === '.tracking-button' && name === 'trigger' ? wrapper.trigger
                    : null
        ),
        getAttribute: attribute => (
            attribute === 'aria-expanded' ? String(wrapper.shown) : null
        ),
        // Alpine hides the list; a hidden element has no offsetParent
        get offsetParent() { return wrapper.shown ? wrapper : null; },
    });
    wrapper.trigger = element('trigger');
    wrapper.items = Array.from({ length: count }, (_, index) => element('item' + index));
    wrapper.querySelector = selector => (
        selector === '.tracking-button' ? wrapper.trigger : null
    );
    wrapper.querySelectorAll = selector => (
        selector === '[role="menuitem"]' ? wrapper.items : []
    );
    return wrapper;
}

/** Press `key` on `target`; what happened. */
function press(key, target, modifiers = {}) {
    let prevented = false;
    document.activeElement = target;
    dispatched.length = 0;
    listeners.keydown({
        key, target, preventDefault: () => { prevented = true; }, ...modifiers,
    });
    return {
        focus: document.activeElement && document.activeElement.name,
        prevented,
        dispatched: dispatched.slice(),
    };
}

function click(target, detail) {
    document.activeElement = target;
    frames.length = 0;
    listeners['click:capture']({ target, detail });
}

const out = {};

out.nextIndex = {
    downFromFirst: MediaTracking.nextIndex('ArrowDown', 0, 3),
    downFromLast: MediaTracking.nextIndex('ArrowDown', 2, 3),
    downFromTheButton: MediaTracking.nextIndex('ArrowDown', -1, 3),
    upFromFirst: MediaTracking.nextIndex('ArrowUp', 0, 3),
    upFromLast: MediaTracking.nextIndex('ArrowUp', 2, 3),
    upFromTheButton: MediaTracking.nextIndex('ArrowUp', -1, 3),
    home: MediaTracking.nextIndex('Home', 2, 3),
    end: MediaTracking.nextIndex('End', 0, 3),
};

let menu = build(3);
out.downFromAnItem = press('ArrowDown', menu.items[0]);
out.downWraps = press('ArrowDown', menu.items[2]);
out.upWraps = press('ArrowUp', menu.items[0]);
out.home = press('Home', menu.items[2]);
out.end = press('End', menu.items[0]);
out.downFromTheButtonOfAnOpenMenu = press('ArrowDown', menu.trigger);
out.upFromTheButtonOfAnOpenMenu = press('ArrowUp', menu.trigger);

out.tabInTheMenu = press('Tab', menu.items[1]);
out.escapeInTheMenu = press('Escape', menu.items[1]);
out.tabOnTheButton = press('Tab', menu.trigger);
out.escapeOnTheButton = press('Escape', menu.trigger);
out.anotherKeyInTheMenu = press('a', menu.items[1]);
out.commandDownInTheMenu = press('ArrowDown', menu.items[1], { metaKey: true });
out.controlHomeInTheMenu = press('Home', menu.items[1], { ctrlKey: true });
out.altUpOnTheButton = press('ArrowUp', menu.trigger, { altKey: true });

// A menu that is closed
menu = build(3, { open: false });
out.downOnAClosedButton = { ...press('ArrowDown', menu.trigger), clicks: menu.trigger.clicks };
out.upOnAClosedButton = { ...press('ArrowUp', menu.trigger), clicks: menu.trigger.clicks };
out.homeOnAClosedButton = { ...press('Home', menu.trigger), clicks: menu.trigger.clicks };

// Quick-mark mode: a click on the button applies the picked status, so an
// arrow must not be turned into one
globalThis.QuickMark = { active: scope => (scope === 'album' ? 'listened' : '') };
menu = build(3, { open: false });
out.downOnAClosedButtonInQuickMark = {
    ...press('ArrowDown', menu.trigger), clicks: menu.trigger.clicks,
};
// Enter there is a click that marks: no menu is coming, so nothing waits
click(menu.trigger, 0);
out.framesWaitedForInQuickMark = frames.length;
menu = build(3, { open: false });
menu.dataset = { trackingScope: 'game' };
out.downOnAClosedButtonInAnotherScope = {
    ...press('ArrowDown', menu.trigger), clicks: menu.trigger.clicks,
};
delete globalThis.QuickMark;

// A key somewhere else on the page
const elsewhere = { name: 'elsewhere', closest: () => null, focus() {} };
out.keyOutsideAnyButton = press('ArrowDown', elsewhere);
out.keyOnTheDocument = press('ArrowDown', {});

// Something inside the wrapper that is neither the button nor an item
menu = build(3);
const stray = { name: 'stray', closest: () => menu, focus() { document.activeElement = this; } };
out.keyOnSomethingElseInTheWrapper = press('ArrowDown', stray);

// Opening from the keyboard: Enter or Space is a click whose detail is 0
menu = build(3, { open: false });
click(menu.trigger, 0);
out.framesWaitedFor = frames.length;
menu.shown = true;  // Alpine shows the list
frames.shift()();
out.keyboardOpenFocuses = document.activeElement.name;

menu = build(3, { open: false });
click(menu.trigger, 1);
out.pointerOpenLeavesFocus = { focus: document.activeElement.name, frames: frames.length };

menu = build(3, { open: true });
click(menu.trigger, 0);
out.keyboardCloseLeavesFocus = { focus: document.activeElement.name, frames: frames.length };

click(menu.items[0], 0);
out.aClickOnAnItemIsNotTheButtons = { focus: document.activeElement.name, frames: frames.length };

// A menu that never shows (quick-mark mode took the click): it gives up
menu = build(3, { open: false });
click(menu.trigger, 0);
let waited = 0;
while (frames.length) { frames.shift()(); waited += 1; }
out.givesUpAfter = waited;
out.focusWhenItNeverShowed = document.activeElement.name;

console.log(JSON.stringify(out));
