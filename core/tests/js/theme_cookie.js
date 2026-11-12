/**
 * The head's theme script (games/templates/includes/_theme_script.html) on
 * each kind of host, for core/tests/test_theme_cookie_js.py: where it keeps
 * the choice, and that a choice made is the one the next page shows.
 *
 *   node core/tests/js/theme_cookie.js
 *
 * The cookie jar follows a browser's rules as far as they matter here: a
 * cookie with a Domain is kept only if the host is that domain or under it,
 * never for an address and never for a single label ("localhost", which
 * Chrome refuses); one without is the host's alone; a host is sent both, the
 * older first.
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..', '..', '..');
const template = fs.readFileSync(
    path.join(root, 'games/templates/includes/_theme_script.html'), 'utf8');
const script = template.match(/<script[^>]*>([\s\S]*?)<\/script>/)[1];

function browser() {
    const jar = [];
    const storage = {};
    const isAddress = host => /^[\d.]+$/.test(host) || host.includes(':');
    const visibleTo = host => jar.filter(cookie => cookie.domain
        ? host === cookie.domain || host.endsWith('.' + cookie.domain)
        : cookie.host === host);

    function set(host, text) {
        const [pair, ...attributes] = text.split(';').map(part => part.trim());
        const [name, value] = pair.split('=');
        const given = Object.fromEntries(attributes.map(attribute => {
            const [key, ...rest] = attribute.split('=');
            return [key.toLowerCase(), rest.join('=')];
        }));
        let domain = null;
        if ('domain' in given) {
            domain = given.domain.replace(/^\./, '');
            const under = host === domain || host.endsWith('.' + domain);
            if (!under || isAddress(host) || !domain.includes('.')) return;
        }
        const at = jar.findIndex(cookie => cookie.name === name &&
            cookie.domain === domain && (domain || cookie.host === host));
        if (at !== -1) jar.splice(at, 1);
        if (given['max-age'] === '0') return;
        jar.push({ name, value, domain, host: domain ? null : host });
    }

    /** One page load on `host`: runs the script, answers what it left. */
    function load(host, prefersLight = false) {
        const page = {
            location: { hostname: host },
            localStorage: {
                getItem: key => (key in storage[host] ? storage[host][key] : null),
                setItem: (key, value) => { storage[host][key] = String(value); },
            },
            matchMedia: () => ({ matches: prefersLight }),
            document: {
                documentElement: { setAttribute(name, value) { page.theme = value; } },
                get cookie() {
                    return visibleTo(host).map(c => `${c.name}=${c.value}`).join('; ');
                },
                set cookie(text) { set(host, text); },
            },
        };
        storage[host] = storage[host] || {};
        page.window = page;
        vm.runInNewContext(script, page);
        return page;
    }

    /** The toggle, as `setTheme` in base.html: storage, then the cookie. */
    function choose(page, theme) {
        page.localStorage.setItem('theme', theme);
        page.saveThemeCookie(theme);
    }

    return {
        load,
        choose,
        set,
        cookies: host => visibleTo(host)
            .map(c => `${c.name}=${c.value}${c.domain ? '; domain=' + c.domain : ''}`),
    };
}

const output = {};

// A choice made on a host is the next page's, for each kind of host
for (const host of ['127.0.0.1', '[::1]', 'localhost', 'games.localhost',
    'games.acclaimedmedia.org', 'acclaimedmedia.org']) {
    const tab = browser();
    const first = tab.load(host).theme;
    tab.choose(tab.load(host), 'lofi');
    output[host] = { first, next: tab.load(host).theme, cookies: tab.cookies(host) };
}

// A host-only cookie already there, which the toggle has to be able to
// change: 127.0.0.1's cookies are shared by every port
for (const host of ['127.0.0.1', 'games.acclaimedmedia.org']) {
    const tab = browser();
    tab.set(host, 'theme=lofi;path=/');
    const before = tab.load(host).theme;
    tab.choose(tab.load(host), 'forest');
    output['stale on ' + host] = {
        before, next: tab.load(host).theme, cookies: tab.cookies(host),
    };
}

// Production: chosen on games, shown on music and the landing page
{
    const tab = browser();
    tab.choose(tab.load('games.acclaimedmedia.org'), 'lofi');
    output.acrossSites = {
        music: tab.load('music.acclaimedmedia.org').theme,
        landing: tab.load('acclaimedmedia.org').theme,
    };
}

process.stdout.write(JSON.stringify(output));
