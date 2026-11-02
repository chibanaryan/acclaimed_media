/**
 * Browser smoke test: loads the main pages in Chrome at desktop and phone
 * widths, opens the mobile filter sheet, and fails on any uncaught error,
 * Alpine expression error or Content-Security-Policy violation.
 *
 *   node scripts/browser_smoke.js http://127.0.0.1:8000
 *
 * The argument names the dev server; its port is all that is used. Each site
 * is its own host (core/sites.py), so the pages are visited as
 * localhost:PORT (the landing page), games.localhost:PORT and
 * music.localhost:PORT - the hosts runserver answers under DEBUG.
 *
 * Needs puppeteer-core and Chrome (CHROME_PATH, or the usual install path).
 * CI's `browser` job runs it against `runserver` on scripts/smoke_seed.py's
 * data. These are the failures no Python test sees: a template binding that
 * only throws in the browser, or an inline script the CSP would refuse. It also
 * checks that Back survives a filter change made while the engine loads,
 * that a server Load More survives the engine's takeover and a view toggle,
 * that music's takeover aborts only the requests it answers, that a games
 * jump filters once and Clear All after it adds no history entry, that a
 * year range the corpus does not reach shows and can be cleared, and that
 * the tab title reads as a reload of the address would. And, on music,
 * what the engine taking the page over must not break: a click out of the
 * search, a mark under a status filter, a failed filter request, Back onto
 * an entry htmx pushed or saved, a server Load More, and the jump box.
 */
const puppeteer = require('puppeteer-core');

const port = new URL(process.argv[2] || 'http://127.0.0.1:8000').port || '80';
const root = `http://localhost:${port}`;
const games = `http://games.localhost:${port}`;
const music = `http://music.localhost:${port}`;
const chrome = process.env.CHROME_PATH ||
    (process.platform === 'darwin'
        ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
        : '/usr/bin/google-chrome');
const pages = [
    root + '/', root + '/page/no-such-page/',
    ...['/', '/games/1990s/', '/game/smoke-game-1/', '/developers/',
        '/developers/?sort=name', '/developers/nintendo/', '/lists/', '/blog/',
        '/no-such-page/'].map(path => games + path),
    ...['/', '/artists/', '/artists/smoke-band/', '/smoke-album-1/', '/lists/',
        '/genres/smoke-rock/', '/no-such-page/'].map(path => music + path),
];

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

/** Clicks the first visible button whose text matches, if there is one. */
const press = (page, label) => page.evaluate(source => {
    const button = [...document.querySelectorAll('button')].find(
        b => b.offsetParent && new RegExp(source).test(b.textContent.trim())
    );
    if (button) button.click();
}, label.source);

/**
 * Holds the engine's data, and whatever request `isServerWork` picks out, until
 * the check lets them go. Returns the two held requests as they arrive.
 */
async function holdEngineLoad(page, { site, data }, isServerWork) {
    const held = { data: null, server: null };
    await page.setRequestInterception(true);
    page.on('request', request => {
        const url = request.url();
        if (url.startsWith(site + data) && !url.includes('smoke=1')) {
            held.data = request;
        } else if (isServerWork(request)) {
            held.server = request;
        } else {
            request.continue();
        }
    });
    return held;
}

/** Waits for both held requests. Answers with what went wrong, if anything. */
async function bothHeld(held, site) {
    for (let tries = 0; !(held.data && held.server) && tries < 200; tries += 1) {
        await sleep(50);
    }
    if (!held.data) return `${site}: the engine never asked for its data`;
    return held.server ? null : `${site}: the click sent no server request`;
}

/** Lets the engine load, and its server request go only once it is ready. */
async function releaseAfterEngine(page, held, { site, data, ready }, element) {
    const body = await page.evaluate(
        url => fetch(url + '?smoke=1').then(response => response.text()), site + data
    );
    await held.data.respond({ status: 200, contentType: 'application/json', body });
    await page.waitForFunction(ready, {}, element);
    await held.server.continue().catch(() => {});
}

/**
 * The engine finishing before a click reached the URL used to replace the entry
 * the click was leaving, so Back never reached the unfiltered page, and on
 * music the click's server render then landed on top of the engine's. That
 * render is held here too, so that the engine always wins the race. Answers
 * as above.
 */
async function checkBackAcrossEngineLoad(page, engine) {
    const { site, render } = engine;
    await page.setViewport({ width: 1440, height: 900 });
    const held = await holdEngineLoad(page, engine, request =>
        request.url().startsWith(site + render) &&
        ['xhr', 'fetch'].includes(request.resourceType()));
    await page.goto(site + '/', { waitUntil: 'load' });
    const decade = await page.waitForSelector('.year-grid-decade[title^="1990s:"]');
    await sleep(1000);
    const entries = await page.evaluate(() => history.length);
    await decade.click();
    const missing = await bothHeld(held, site);
    if (missing) return missing;
    await releaseAfterEngine(page, held, engine, decade);
    await page.waitForFunction(count => history.length > count, {}, entries);
    await sleep(300);
    const added = await page.evaluate(() => history.length) - entries;
    const filtered = page.url();
    await page.evaluate(() => history.back());
    await sleep(800);
    const landed = page.url();
    if (added !== 1) return `${site}: one click added ${added} history entries`;
    return landed === site + '/' ? null : `Back from ${filtered} landed on ${landed}`;
}

/**
 * A server page of rows on its way as the engine takes over would land behind
 * the renderer's back. Games' first render replaces the button, so the page is
 * dropped, and music's engine aborts it. Either way the engine answers the
 * click, so there is exactly one more page and no row twice.
 */
async function checkLoadMoreAcrossEngineLoad(page, engine) {
    const { site, loadMorePath, rows } = engine;
    await page.setViewport({ width: 1440, height: 900 });
    const held = await holdEngineLoad(page, engine, request =>
        request.url().includes('append=true'));
    await page.goto(site + loadMorePath, { waitUntil: 'load' });
    const button = await page.waitForSelector('.load-more-button');
    const decade = await page.waitForSelector('.year-grid-decade');
    const total = Number(await page.$eval('.jump-to-rank-input', box => box.dataset.total));
    await sleep(1000);
    await button.click();
    const missing = await bothHeld(held, site);
    if (missing) return missing;
    await releaseAfterEngine(page, held, engine, decade);
    await sleep(800);
    const count = await page.$$eval(rows, found => found.length);
    return count === Math.min(200, total) ? null : `${site}: ${count} rows of ${total}`;
}

/** Starts the games engine, as focusing a jump box does, and waits for it. */
async function startGamesEngine(page) {
    const component = await page.waitForSelector('[x-data*="filterComponent"]');
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('acclaimed:need-csf')));
    await page.waitForFunction(element => Alpine.$data(element).clientFilterReady, {}, component);
    return component;
}

/**
 * A games jump filtered the whole corpus three times, where once gives it every
 * game it needs. And Clear All from a jumped list, whose filters it leaves as
 * they were, pushed `/` over `/`, so Back needed two presses. Answers as above.
 */
async function checkJumpThenClearAll(page) {
    await page.setViewport({ width: 1440, height: 900 });
    await page.goto(games + '/', { waitUntil: 'networkidle2' });
    await startGamesEngine(page);
    await page.evaluate(() => {
        const csf = getClientSideFiltering();
        const applyFilters = csf.applyFilters.bind(csf);
        window.__filterPasses = 0;
        csf.applyFilters = (...args) => {
            window.__filterPasses += 1;
            return applyFilters(...args);
        };
    });
    const box = (await page.evaluateHandle(() => [...document.querySelectorAll(
        '.jump-to-rank-input')].find(input => input.offsetParent))).asElement();
    await box.type('110');
    await box.press('Enter');
    await sleep(500);
    const passes = await page.evaluate(() => window.__filterPasses);
    if (passes !== 1) return `games: a jump filtered the corpus ${passes} times`;
    const entries = await page.evaluate(() => history.length);
    await press(page, /^Clear All$/);
    await sleep(800);
    const added = await page.evaluate(() => history.length) - entries;
    if (added !== 0) return `games: Clear All after a jump added ${added} history entries`;
    const start = await page.evaluate(() => getClientSideFiltering().renderer.windowStart);
    return start === 0 ? null : `games: Clear All left the list starting at #${start + 1}`;
}

/**
 * A view toggle once the engine is ready re-renders the list, and with it the
 * Load More button a server page was on its way to, so the page was dropped
 * and the click went unanswered. Answers as above.
 */
async function checkLoadMoreAcrossViewToggle(page) {
    await page.setViewport({ width: 1440, height: 900 });
    let held = null;
    await page.setRequestInterception(true);
    page.on('request', request => {
        if (request.url().includes('append=true')) {
            held = request;
        } else {
            request.continue();
        }
    });
    await page.goto(games + '/', { waitUntil: 'networkidle2' });
    const button = await page.waitForSelector('.load-more-button');
    const total = Number(await page.$eval('.jump-to-rank-input', box => box.dataset.total));
    await button.click();
    for (let tries = 0; !held && tries < 200; tries += 1) await sleep(50);
    if (!held) return 'games: Load More sent no server request';
    const component = await startGamesEngine(page);
    await page.evaluate(element => Alpine.$data(element).setViewMode('grid'), component);
    await held.continue();
    await sleep(800);
    const ids = await page.$$eval('.game-card-grid', found => found.map(card => card.id));
    if (new Set(ids).size !== ids.length) return 'games: a card is shown twice';
    return ids.length === Math.min(200, total) ? null : `games: ${ids.length} cards of ${total}`;
}

/**
 * A music Load More whose button a filter change swaps out before the engine
 * is ready: its afterRequest fires on the detached button, out of the
 * engine's hearing, so the takeover once took the finished request for one
 * still to answer and appended a page nobody asked for, and could not abort
 * one still on its way. `landed` lets the page's response arrive before the
 * engine does, or holds it until after. Answers as above.
 */
async function checkDetachedLoadMoreAcrossEngineLoad(page, engine, landed) {
    await page.setViewport({ width: 1440, height: 900 });
    const held = await holdEngineLoad(page, engine, request =>
        request.url().includes('append=true'));
    await page.goto(music + '/', { waitUntil: 'load' });
    const button = await page.waitForSelector('.load-more-button');
    const decade = await page.waitForSelector('.year-grid-decade');
    await sleep(1000);
    await button.click();
    const missing = await bothHeld(held, music);
    if (missing) return missing;
    // A server filter render, which replaces the results and the button. A
    // change with a detail, as commit() sends: the form answers no other
    await page.evaluate(() => {
        const form = document.getElementById('album-filters');
        form.querySelector('[name="dir"]').value = 'desc';
        form.dispatchEvent(new CustomEvent('change', { bubbles: true, detail: {} }));
    });
    await page.waitForFunction(() => location.search.includes('dir=desc'));
    // What the Load More container holds: the next page's URL, or its text
    const nextPage = () => page.$eval('.load-more-container', box => {
        const more = box.querySelector('.load-more-button');
        return more ? more.getAttribute('hx-get') : box.textContent.trim();
    });
    await page.waitForFunction(() => {
        const more = document.querySelector('.load-more-container .load-more-button');
        return more && (more.getAttribute('hx-get') || '').includes('dir=desc');
    });
    if (landed) {
        await held.server.continue();
        // Landed once its out-of-band container has replaced the live one
        await page.waitForFunction(() => {
            const more = document.querySelector('.load-more-container .load-more-button');
            return !more || !(more.getAttribute('hx-get') || '').includes('dir=desc');
        });
    }
    const rows = '#album-list-container .media-row-wrapper';
    const before = await page.$$eval(rows, found => found.length);
    await releaseAfterEngine(page, held, engine, decade);
    await sleep(800);
    const after = await page.$$eval(rows, found => found.length);
    if (after !== before) return `the takeover turned ${before} rows into ${after}`;
    // Landed, its out-of-band button has already replaced the live one (an
    // older race, ROADMAP). Aborted, it cannot: the button is still the one
    // the descending render drew.
    if (landed) return null;
    const next = await nextPage();
    return next && next.includes('dir=desc') ? null : `the stale page left "${next}"`;
}

/**
 * The takeover aborts the filter and Load More requests it overtakes, and
 * nothing else: a row's listen-status POST in flight as the engine loads has
 * to reach the server and answer. A stand-in button posts from inside the
 * results, as a row's does, and the POST is held across the takeover.
 * Answers as above.
 */
async function checkRowPostSurvivesTheTakeover(page, engine) {
    await page.setViewport({ width: 1440, height: 900 });
    const held = await holdEngineLoad(page, engine, request =>
        request.method() === 'POST' && request.url().includes('smoke-post'));
    await page.goto(music + '/', { waitUntil: 'load' });
    const decade = await page.waitForSelector('.year-grid-decade');
    await sleep(1000);
    await page.evaluate(() => {
        const button = document.createElement('button');
        button.id = 'smoke-post';
        button.setAttribute('hx-post', '/healthz/?smoke-post');
        button.setAttribute('hx-swap', 'none');
        button.addEventListener('htmx:afterRequest', event => {
            window.smokePostStatus = event.detail.successful
                ? event.detail.xhr.status : 'failed';
        });
        document.getElementById('album-list-container').prepend(button);
        htmx.process(button);
        button.click();
    });
    const missing = await bothHeld(held, music);
    if (missing) return missing;
    // Answered rather than continued: /healthz/ takes no POST
    const post = held.server;
    held.server = { continue: () => Promise.resolve() };
    await releaseAfterEngine(page, held, engine, decade);
    await post.respond({ status: 204, body: '' }).catch(() => {});
    await page.waitForFunction(() => window.smokePostStatus !== undefined);
    const status = await page.evaluate(() => window.smokePostStatus);
    return status === 204 ? null : `the takeover left a row's POST ${status}`;
}

/**
 * Music's engine takes the page over without touching it: a URL it read as
 * unrendered would be replaced, and with it the search. On a phone, with the
 * data already held, the engine beats Alpine to the form. Answers as above.
 */
async function checkEngineLeavesTheUrlAlone(page, url) {
    await page.setViewport({ width: 420, height: 860 });
    await page.goto(url, { waitUntil: 'networkidle2' });
    await page.goto(url, { waitUntil: 'networkidle2' });
    await sleep(500);
    return page.url() === url ? null : `${url} became ${page.url()}`;
}

const albumRows = '#album-list-container .media-row-wrapper';
const musicReady = element => Alpine.$data(element)._clientEngineReady();

/** Opens music's rankings at `path` and waits for its engine to take over. */
async function openMusicEngine(page, path = '/') {
    await page.setViewport({ width: 1440, height: 900 });
    await page.goto(music + path, { waitUntil: 'networkidle2' });
    const decade = await page.waitForSelector('.year-grid-decade');
    await page.waitForFunction(musicReady, {}, decade);
}

/**
 * The debounced commit and the typing timer both answered one search, so each
 * search left two identical entries and Back needed two presses, and then,
 * with the entries deduplicated, still rendered the list twice. Answers as
 * above.
 */
async function checkSearchAddsOneEntry(page) {
    await openMusicEngine(page);
    const entries = await page.evaluate(() => history.length);
    await page.evaluate(() => {
        const csf = getAlbumClientSideFiltering();
        const apply = csf.applyFilters.bind(csf);
        window.__renders = 0;
        csf.applyFilters = (...args) => {
            window.__renders += 1;
            return apply(...args);
        };
    });
    await page.type('#album-filters input[name="q"]', 'smoke');
    await sleep(1200);
    const added = await page.evaluate(() => history.length) - entries;
    const renders = await page.evaluate(() => window.__renders);
    if (added !== 1) return `one search added ${added} history entries`;
    return renders === 1 ? null : `one search rendered the list ${renders} times`;
}

/**
 * Leaving the search box fires the input's own `change`, and the engine
 * re-rendered on it during the mousedown, so the button under the pointer was
 * replaced and the first click after a search did nothing. Answers as above.
 */
async function checkClickOutOfTheSearch(page) {
    await openMusicEngine(page);
    await page.type('#album-filters input[name="q"]', 'smoke');
    await sleep(1200);
    const button = await page.$('.load-more-button');
    if (!button) return 'a search for smoke left no Load More';
    await button.click();
    await sleep(500);
    const count = await page.$$eval(albumRows, found => found.length);
    return count === 120 ? null : `the click out of the search loaded ${count} rows`;
}

/**
 * Marking an album that a status filter then leaves out re-rendered the list
 * from the top, so a reader 60 rows down lost their place. Only that row may
 * go, with the rows after it renumbered. Simulated, as a signed-out page has
 * no button to press: the Sets are what media-tracking.js changes before it
 * announces the toggle. Answers as above.
 */
async function checkMarkingKeepsThePlace(page) {
    await openMusicEngine(page, '/?listened=no');
    await (await page.$('.load-more-button')).click();
    await sleep(500);
    const before = await page.evaluate(selector => {
        const rows = [...document.querySelectorAll(selector)];
        rows[59].scrollIntoView();
        const rank = row => parseInt(row.querySelector('[data-slot="rank"]').textContent, 10);
        return {
            count: rows.length,
            first: rows[0].id,
            marked: rows[59].id,
            next: rows[60].id,
            nextRank: rank(rows[60]),
            scrollY: window.scrollY,
        };
    }, albumRows);
    if (before.count !== 120) return `Load More gave ${before.count} rows`;
    await page.evaluate(id => {
        const albumId = parseInt(id.replace('music-', ''), 10);
        window.isAuthenticated = true;
        window.listenedAlbumIds.add(albumId);
        window.dispatchEvent(new CustomEvent('album-status-changed', {
            detail: { id: albumId, status: 'listened' },
        }));
    }, before.marked);
    await sleep(500);
    const after = await page.evaluate(selector => {
        const rows = [...document.querySelectorAll(selector)];
        return {
            count: rows.length,
            first: rows[0].id,
            at60: rows[59] && rows[59].id,
            rank60: rows[59] &&
                parseInt(rows[59].querySelector('[data-slot="rank"]').textContent, 10),
            scrollY: window.scrollY,
        };
    }, albumRows);
    if (after.count !== 119) return `marking left ${after.count} rows of 119`;
    if (after.first !== before.first || after.at60 !== before.next) {
        return 'marking moved the rows around the one that left';
    }
    if (after.rank60 !== before.nextRank - 1) {
        return `the row after the marked one reads #${after.rank60}`;
    }
    const moved = Math.abs(after.scrollY - before.scrollY);
    return moved < 100 ? null : `marking scrolled the page ${moved}px`;
}

/**
 * A filter request that failed before the engine loaded left the form on the
 * filters it asked for while the list and the URL stayed on the old ones, and
 * the engine's first Load More then appended the other filter's rows. The
 * engine renders the form's filters as it takes over. Answers as above.
 */
async function checkFailedFilterRequest(page) {
    const engine = { site: music, data: '/api/all/', ready: musicReady };
    await page.setViewport({ width: 1440, height: 900 });
    const held = await holdEngineLoad(page, engine, request =>
        request.url().startsWith(music + '/?') &&
        ['xhr', 'fetch'].includes(request.resourceType()));
    await page.goto(music + '/', { waitUntil: 'load' });
    const decade = await page.waitForSelector('.year-grid-decade[title^="1990s:"]');
    await sleep(1000);
    await decade.click();
    const missing = await bothHeld(held, music);
    if (missing) return missing;
    await held.server.respond({ status: 500, contentType: 'text/html', body: 'boom' });
    await sleep(500);
    await releaseAfterEngine(page, held, engine, decade);
    await sleep(500);
    if (!page.url().includes('start=1990')) return `the engine left the URL on ${page.url()}`;
    const years = await page.$$eval(`${albumRows} [data-slot="year"]`,
        found => found.map(slot => parseInt(slot.textContent.replace(/\D/g, ''), 10)));
    const outside = years.filter(year => year < 1990 || year > 1999);
    if (outside.length) return `the list after the failure holds ${outside.length} albums outside the 1990s`;
    return years.length === 20 ? null : `the 1990s list has ${years.length} rows, not 20`;
}

/**
 * A server Load More pushed its own address, `?page=2&append=true`, and Back,
 * Forward or a reload onto it rendered the rows alone, with no page. It is
 * rows to append, not an address, so it pushes nothing. Answers as above.
 */
async function checkServerLoadMoreAddsNoEntry(page) {
    await page.setViewport({ width: 1440, height: 900 });
    const held = await holdMusicData(page);
    await page.goto(music + '/', { waitUntil: 'load' });
    await sleep(1000);
    const entries = await page.evaluate(() => history.length);
    await (await page.waitForSelector('.load-more-button')).click();
    await page.waitForFunction(
        rows => document.querySelectorAll(rows).length > 100, {}, albumRows
    );
    await sleep(300);
    const added = await page.evaluate(() => history.length) - entries;
    const url = page.url();
    await held.release();
    if (url.includes('append')) return `a server Load More moved the address to ${url}`;
    return added ? `a server Load More added ${added} history entries` : null;
}

/**
 * A search still being typed as the engine takes over is not a form left
 * ahead by a failed request: rendering it then pushed the half-typed query,
 * and the commit pushed the whole one beside it. Answers as above.
 */
async function checkTypingAcrossTheTakeover(page) {
    const engine = { site: music, data: '/api/all/', ready: musicReady };
    await page.setViewport({ width: 1440, height: 900 });
    // The half-typed search's own request, held so that it is still on its
    // way when the engine takes over, however slow the machine
    const held = await holdEngineLoad(page, engine, request =>
        request.url().includes('q=smo') && !request.url().includes('q=smoke') &&
        ['xhr', 'fetch'].includes(request.resourceType()));
    await page.goto(music + '/', { waitUntil: 'load' });
    const decade = await page.waitForSelector('.year-grid-decade');
    await sleep(1000);
    const entries = await page.evaluate(() => history.length);
    const search = '#album-filters input[name="q"]';
    await page.type(search, 'smo');
    const missing = await bothHeld(held, music);
    if (missing) return missing;
    await releaseAfterEngine(page, held, engine, decade);
    await page.type(search, 'ke');
    await sleep(1500);
    const added = await page.evaluate(() => history.length) - entries;
    if (!page.url().endsWith('?q=smoke')) return `the search ended on ${page.url()}`;
    return added === 1 ? null : `one search typed across the takeover added ${added} entries`;
}

/**
 * Back onto an artist's albums after Clear All emptied the artist. The heading
 * names the artist from the form's field, which the controls do not restore
 * from the URL and the engine's popstate listener does, so this rests on the
 * engine writing the field before the heading is rebuilt. Answers as above.
 */
async function checkBackKeepsTheArtistInTheHeading(page) {
    await openMusicEngine(page, '/?artists=smoke-band');
    await press(page, /^Clear All$/);
    await page.waitForFunction(() => !location.search.includes('artists'));
    await sleep(300);
    await page.evaluate(() => history.back());
    await sleep(800);
    const heading = await page.$eval('#search-title-text', title => title.textContent);
    return /Smoke Band/.test(heading) ? null : `Back onto the artist's albums reads "${heading}"`;
}

/** Holds music's data, and answers it when `release()` is called. */
async function holdMusicData(page) {
    const held = { data: null };
    await page.setRequestInterception(true);
    page.on('request', request => {
        if (request.url().startsWith(music + '/api/all/') &&
                !request.url().includes('smoke=1')) {
            held.data = request;
        } else {
            request.continue();
        }
    });
    held.release = async () => {
        for (let tries = 0; !held.data && tries < 200; tries += 1) await sleep(50);
        const body = await page.evaluate(
            url => fetch(url + '?smoke=1').then(response => response.text()),
            music + '/api/all/'
        );
        await held.data.respond({ status: 200, contentType: 'application/json', body });
        const decade = await page.waitForSelector('.year-grid-decade');
        await page.waitForFunction(musicReady, {}, decade);
    };
    return held;
}

/** Clicks a decade and waits for the URL to name it. */
async function clickDecade(page, decade) {
    const element = await page.waitForSelector(`.year-grid-decade[title^="${decade}s:"]`);
    await element.click();
    await page.waitForFunction(
        year => location.search.includes(`start=${year}`), {}, decade
    );
    await sleep(300);
}

/** Answers with what is wrong with the list after Load More, if anything. */
async function loadMoreProblem(page, label) {
    await page.evaluate(() => { window.__form = document.getElementById('album-filters'); });
    const button = await page.$('.load-more-button');
    const rowsBefore = await page.$$eval(albumRows, found => found.length);
    if (button) {
        await button.click();
        await sleep(800);
    }
    const ids = await page.$$eval(albumRows, found => found.map(row => row.id));
    if (new Set(ids).size !== ids.length) return `${label}: Load More repeated rows`;
    const expected = button ? Math.min(rowsBefore + 100, 120) : rowsBefore;
    return ids.length === expected ? null : `${label}: ${ids.length} rows, not ${expected}`;
}

/**
 * htmx stamps each entry it pushes and, on Back, swaps the whole body back in,
 * leaving the engine wired to a form that is no longer on the page. Answers
 * as above.
 */
async function checkBackOntoAnHtmxEntry(page) {
    await page.setViewport({ width: 1440, height: 900 });
    const held = await holdMusicData(page);
    await page.goto(music + '/', { waitUntil: 'load' });
    await sleep(1000);
    // Pushed by htmx: the engine has no data yet
    await clickDecade(page, 1990);
    await held.release();
    const form = await page.evaluateHandle(() => document.getElementById('album-filters'));
    // Pushed by the engine
    await clickDecade(page, 1980);
    await page.evaluate(() => history.back());
    await sleep(1500);
    const same = await page.evaluate(
        old => old === document.getElementById('album-filters'), form
    );
    if (!same) return 'Back onto an htmx entry replaced the engine\'s form';
    if (!page.url().includes('start=1990')) return `Back landed on ${page.url()}`;
    return loadMoreProblem(page, 'Back onto an htmx entry');
}

/** The same Back, pressed before the engine has loaded. Answers as above. */
async function checkBackBeforeTheEngine(page) {
    await page.setViewport({ width: 1440, height: 900 });
    const held = await holdMusicData(page);
    await page.goto(music + '/', { waitUntil: 'load' });
    await sleep(1000);
    await clickDecade(page, 1990);
    await page.evaluate(() => history.back());
    await sleep(1500);
    await held.release();
    // A filter change made once the engine is ready
    await clickDecade(page, 1980);
    const pushed = await page.evaluate(() => [...document.querySelectorAll(
        '#album-list-container .media-row-wrapper'
    )].length);
    if (!pushed) return 'the decade after Back rendered no rows';
    return loadMoreProblem(page, 'Back before the engine');
}

/**
 * Snapshots htmx saved of this page, on an earlier visit or in a tab still on
 * the old markup, are in localStorage, and htmx restores a stored one before
 * it would reload. So until the engine answers Back, the page reloads instead
 * of letting htmx restore anything. Answers as above.
 */
async function checkBackPastAnOldSnapshot(page) {
    await page.setViewport({ width: 1440, height: 900 });
    const held = await holdMusicData(page);
    await page.goto(music + '/', { waitUntil: 'load' });
    await sleep(1000);
    await clickDecade(page, 1990);
    // As another tab would, after this page loaded
    await page.evaluate(() => localStorage.setItem('htmx-history-cache', JSON.stringify([{
        url: '/',
        content: '<form id="album-filters"></form><p id="stale">stale</p>',
        title: 'stale',
        scroll: 0,
    }])));
    await page.evaluate(() => history.back());
    await sleep(1500);
    if (await page.$('#stale')) return 'Back restored a stored snapshot';
    await held.release();
    return (await page.$('#album-filters')) ? null : 'Back left no filter form';
}

/**
 * The jump box is answered by the engine alone, so without its data it took a
 * number and ignored Enter. It waits for the engine, disabled. Answers as
 * above.
 */
async function checkJumpBoxWaitsForTheEngine(page) {
    await page.setViewport({ width: 1440, height: 900 });
    await page.setRequestInterception(true);
    page.on('request', request => {
        if (request.url().startsWith(music + '/api/all/')) {
            request.respond({ status: 500, contentType: 'text/plain', body: 'boom' });
        } else {
            request.continue();
        }
    });
    await page.goto(music + '/', { waitUntil: 'networkidle2' });
    await sleep(500);
    const enabled = await page.$$eval('.jump-to-rank-input, .jump-to-rank-btn',
        found => found.filter(element => !element.disabled).length);
    return enabled ? `${enabled} jump controls are live without the engine` : null;
}

/** And comes on once the engine is ready. Answers as above. */
async function checkJumpBoxComesOn(page) {
    await openMusicEngine(page);
    const disabled = await page.$$eval('.jump-to-rank-input, .jump-to-rank-btn',
        found => found.filter(element => element.disabled).length);
    return disabled ? `${disabled} jump controls stayed off with the engine ready` : null;
}

/**
 * A select with no option for its value falls back to the first one, so a
 * range before the corpus read as its newest year. And an empty result had no
 * list for the engine to render into, so nothing could leave it. Answers as
 * above.
 */
async function checkRangeOutsideTheCorpus(page, site) {
    await page.setViewport({ width: 420, height: 860 });
    await page.goto(`${site}/?start=1900&end=1950`, { waitUntil: 'networkidle2' });
    // Games' engine re-renders a filtered page as it loads, and music's does not
    await page.waitForFunction(() => {
        const games = document.querySelector('[x-data*="filterComponent"]');
        return !games || Alpine.$data(games).clientFilterReady;
    });
    const message = await page.evaluate(
        () => document.querySelector('[id$="-list-container"]').textContent
    );
    if (!/match your filters/.test(message)) {
        return `${site} lost its message that nothing matches`;
    }
    await press(page, /Filters/);
    await sleep(800);
    await press(page, /^Range$/);
    await sleep(300);
    const shown = await page.evaluate(() => ['From year', 'To year'].map(
        name => document.querySelector(`select[aria-label="${name}"]`)
            .selectedOptions[0].textContent
    ));
    if (shown.join() !== '1900,1950') return `${site} From and To show ${shown}`;
    await press(page, /^Clear All Filters$/);
    await page.waitForSelector('[id$="-list-container"] a');
    return null;
}

/**
 * The tab says what a reload of the address would: a filtered page lists its
 * facets and its section, and a landing page or an unfiltered one keeps its
 * heading. Each step's title is checked against the server's for the URL it
 * left. A title the page kept from load came back for any state with the same
 * facets, which on music's /?genres=... named the landing page it had left.
 * Answers as above.
 */
async function checkTabTitleMatchesAReload(page, site, path, steps) {
    await page.setViewport({ width: 1440, height: 900 });
    const ready = async () => {
        const decade = await page.waitForSelector('.year-grid-decade[title^="1990s:"]');
        await page.waitForFunction(element => {
            const data = Alpine.$data(element);
            return data.clientFilterReady ||
                (data._clientEngineReady && data._clientEngineReady());
        }, {}, decade);
        return decade;
    };
    await page.goto(site + path, { waitUntil: 'networkidle2' });
    const decade = await ready();
    const served = () => page.evaluate(async () => {
        const html = await (await fetch(location.href)).text();
        return new DOMParser().parseFromString(html, 'text/html').title;
    });
    const flip = () => page.evaluate(() => [...document.querySelectorAll('button')]
        .find(b => b.offsetParent && b.getAttribute('@click') === 'toggleSortDirection()')
        .click());
    const actions = {
        'the 1990s': () => decade.click(),
        'no 1990s': () => decade.click(),
        'a flipped sort': flip,
        'the sort back': flip,
        'the grid': () => page.evaluate(() => [...document.querySelectorAll('button')]
            .find(b => b.offsetParent && b.getAttribute('@click') === "setViewMode('grid')")
            .click()),
        'Clear All': () => press(page, /^Clear All/),
        Back: () => page.goBack(),
    };
    let short = false;
    for (const step of steps) {
        await actions[step]();
        await sleep(800);
        const [shown, expected] = [await page.title(), await served()];
        if (shown !== expected) {
            return `${site}${path} after ${step}: the tab read "${shown}", ` +
                `a reload of ${page.url()} "${expected}"`;
        }
        short = short || / \| (Music|Games) \| Acclaimed Media$/.test(shown);
    }
    return short ? null : `${site}${path}: no step gave the short tab title`;
}

(async () => {
    const browser = await puppeteer.launch({
        executablePath: chrome,
        headless: true,
        // Chrome resolves *.localhost itself; the rule makes sure of it
        args: ['--no-sandbox', '--host-resolver-rules=MAP *.localhost 127.0.0.1'],
    });
    let failures = 0;
    for (const [width, height] of [[1440, 900], [420, 860]]) {
        for (const url of pages) {
            const page = await browser.newPage();
            await page.setViewport({ width, height });
            const problems = [];
            page.on('pageerror', error => problems.push(`error: ${error.message}`));
            page.on('console', message => {
                if (/Alpine Expression Error/.test(message.text())) {
                    problems.push(message.text().split('\n').slice(0, 3).join(' | '));
                }
            });
            await page.evaluateOnNewDocument(() => {
                window.__csp = [];
                document.addEventListener('securitypolicyviolation', event => {
                    window.__csp.push(`csp: ${event.violatedDirective} ${event.blockedURI}`);
                });
            });
            await page.goto(url, { waitUntil: 'networkidle2' });
            await sleep(1000);
            if (width < 962) {
                // The bottom sheet's contents are only rendered once opened
                await press(page, /Filters/);
                await sleep(800);
                // And the year selects only once their mode is open
                for (const mode of [/^Year$/, /^Range$/]) {
                    await press(page, mode);
                    await sleep(300);
                }
            }
            problems.push(...await page.evaluate(() => window.__csp));
            if (problems.length) {
                failures += 1;
                console.log(`FAIL ${width}px ${url}\n  ${problems.join('\n  ')}`);
            } else {
                console.log(`ok   ${width}px ${url}`);
            }
            await page.close();
        }
    }
    // Each in its own context: game data cached by the pages above would skip
    // the very load these wait on
    const report = async (name, check) => {
        const context = await browser.createBrowserContext();
        const page = await context.newPage();
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        let problem;
        try {
            problem = await check(page) || errors[0];
        } catch (error) {
            problem = `${name}: ${error.message}`;
        } finally {
            await context.close();
        }
        if (problem) failures += 1;
        console.log(problem ? `FAIL ${problem}` : `ok   ${name}`);
    };
    const engines = {
        games: {
            site: games,
            data: '/api/games/all/',
            render: '/games/?',
            ready: element => Alpine.$data(element).clientFilterReady,
            // Any filter: the engine re-renders it, as it does not a bare page
            loadMorePath: '/?sort=name',
            rows: '#game-list-container .game-row-wrapper',
        },
        music: {
            site: music,
            data: '/api/all/',
            render: '/?',
            ready: musicReady,
            loadMorePath: '/',
            rows: '#album-list-container .media-row-wrapper',
        },
    };
    for (const [name, engine] of Object.entries(engines)) {
        await report(`${name} Back across the engine load`,
            page => checkBackAcrossEngineLoad(page, engine));
        await report(`${name} Load More across the engine load`,
            page => checkLoadMoreAcrossEngineLoad(page, engine));
    }
    await report('games jump then Clear All', checkJumpThenClearAll);
    await report('games Load More across a view toggle', checkLoadMoreAcrossViewToggle);
    // The third is spelled as the server would not echo it, which the engine
    // must not read as a form left ahead of the list
    for (const path of ['/?q=smoke', '/genres/smoke-rock/?utm_source=smoke',
        '/?artists=Smoke-Band&genres=0&genres=1']) {
        await report(`music keeps ${path}`,
            page => checkEngineLeavesTheUrlAlone(page, music + path));
    }
    for (const landed of [true, false]) {
        await report(`music Load More swapped out, ${landed ? 'landed' : 'in flight'}`,
            page => checkDetachedLoadMoreAcrossEngineLoad(page, engines.music, landed));
    }
    await report('music row POST across the engine load',
        page => checkRowPostSurvivesTheTakeover(page, engines.music));
    await report('music search adds one entry', checkSearchAddsOneEntry);
    await report('music tab title on a landing page',
        page => checkTabTitleMatchesAReload(page, music, '/genres/smoke-rock/',
            ['the 1990s', 'no 1990s', 'Back', 'Back']));
    // No control picks an artist, so only Back brings one back, and the
    // title reads it from the form field the filtering bundle rewrites
    await report('music tab title with an artist',
        page => checkTabTitleMatchesAReload(page, music, '/?artists=smoke-band',
            ['Clear All', 'Back']));
    await report('games tab title on a landing page',
        page => checkTabTitleMatchesAReload(page, games, '/games/smoke-action/',
            ['a flipped sort', 'the sort back', 'the 1990s', 'Back', 'Back']));
    // A landing path with a query: the engine moves the address to
    // /games/?... as it takes over, and the tab has to follow it there
    await report('games tab title on a landing page with a query',
        page => checkTabTitleMatchesAReload(page, games, '/games/smoke-action/?sort=name',
            ['the grid', 'the 1990s', 'Back']));
    await report('music click out of the search', checkClickOutOfTheSearch);
    await report('music marking keeps the place', checkMarkingKeepsThePlace);
    await report('music failed filter request', checkFailedFilterRequest);
    await report('music Back onto an htmx entry', checkBackOntoAnHtmxEntry);
    await report('music Back before the engine', checkBackBeforeTheEngine);
    await report('music Back past an old snapshot', checkBackPastAnOldSnapshot);
    await report('music Back keeps the artist in the heading', checkBackKeepsTheArtistInTheHeading);
    await report('music typing across the takeover', checkTypingAcrossTheTakeover);
    await report('music server Load More adds no entry', checkServerLoadMoreAddsNoEntry);
    await report('music jump box waits for the engine', checkJumpBoxWaitsForTheEngine);
    await report('music jump box comes on', checkJumpBoxComesOn);
    await report('games empty range', page => checkRangeOutsideTheCorpus(page, games));
    await report('music empty range', page => checkRangeOutsideTheCorpus(page, music));
    await browser.close();
    process.exit(failures ? 1 : 0);
})().catch(error => {
    console.error(error);
    process.exit(1);
});
