/**
 * Browser smoke test: loads the main pages in Chrome at desktop and phone
 * widths, opens the mobile filter sheet, and fails on any uncaught error,
 * Alpine expression error or Content-Security-Policy violation.
 *
 *   node scripts/browser_smoke.js http://127.0.0.1:8000
 *   SMOKE_ONLY='music Load More' node scripts/browser_smoke.js ...
 *
 * SMOKE_ONLY, a regular expression, runs only the named checks after the
 * page loop, and skips the loop.
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

/**
 * Clicks the first visible button whose text matches, and answers whether
 * there was one: a check that goes on without asking has pressed nothing and
 * passed.
 */
const press = (page, label) => page.evaluate(source => {
    const button = [...document.querySelectorAll('button')].find(
        b => b.offsetParent && new RegExp(source).test(b.textContent.trim())
    );
    if (button) button.click();
    return Boolean(button);
}, label.source);

/** The pages with a mobile filter sheet, which the page loop must find and open. */
const sheetPages = new Set([
    games + '/', games + '/games/1990s/', music + '/', music + '/genres/smoke-rock/',
]);

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
 * A server jump the engine's load overtook, then a filter change: when the
 * jump's pages landed the engine made the jump itself, on the new list,
 * undoing the change's return to the top. They are dropped now. Answers as
 * above.
 */
async function checkServerJumpOvertakenByAFilter(page, back = false) {
    const engine = {
        site: games, data: '/api/games/all/',
        ready: element => Alpine.$data(element).clientFilterReady,
    };
    await page.setViewport({ width: 1440, height: 900 });
    const held = await holdEngineLoad(page, engine, request =>
        request.url().includes('append=true'));
    await page.goto(games + '/', { waitUntil: 'load' });
    const component = await page.waitForSelector('[x-data*="filterComponent"]');
    await sleep(1000);
    const box = (await page.evaluateHandle(() => [...document.querySelectorAll(
        '.jump-to-rank-input')].find(input => input.offsetParent))).asElement();
    // One server page: the jump waits 3 s for the engine, held, then fetches
    await box.type('110');
    await box.press('Enter');
    const missing = await bothHeld(held, games);
    if (missing) return missing;
    const body = await page.evaluate(
        url => fetch(url + '?smoke=1').then(response => response.text()),
        games + engine.data
    );
    await held.data.respond({ status: 200, contentType: 'application/json', body });
    await page.waitForFunction(engine.ready, {}, component);
    await page.evaluate(element => Alpine.$data(element).updateSort('name'), component);
    await sleep(500);
    if (back) {
        // Back to the list the jump was asked on, at its top: the same
        // filters, but not the same visit, so the jump is still dropped
        await page.evaluate(() => history.back());
        await sleep(800);
    }
    await held.server.continue().catch(() => {});
    await sleep(800);
    const [start, end] = await page.evaluate(() => {
        const renderer = getClientSideFiltering().renderer;
        return [renderer.windowStart, renderer.windowEnd];
    });
    return start === 0 && end === 100 ? null
        : `games: a server jump overtaken by a sort change${back ? ' and Back' : ''} ` +
            `rendered rows ${start + 1}-${end}`;
}

/**
 * A server jump the engine's load overtook without a render (an unfiltered
 * list), then the engine's own Load More, which redraws the button the
 * jump's pages were on their way to. The list is the same, so the jump is
 * made, not dropped. Answers as above.
 */
async function checkServerJumpAcrossAnEngineLoadMore(page) {
    await page.setViewport({ width: 1440, height: 900 });
    // The jump fetches pages 2 and 3, so every page is held, not the last
    const held = { data: null, pages: [] };
    await page.setRequestInterception(true);
    page.on('request', request => {
        const url = request.url();
        if (url.startsWith(games + '/api/games/all/') && !url.includes('smoke=1')) {
            held.data = request;
        } else if (url.includes('append=true')) {
            held.pages.push(request);
        } else {
            request.continue();
        }
    });
    await page.goto(games + '/', { waitUntil: 'load' });
    const filters = await page.waitForSelector('[x-data*="filterComponent"]');
    await sleep(1000);
    const box = (await page.evaluateHandle(() => [...document.querySelectorAll(
        '.jump-to-rank-input')].find(input => input.offsetParent))).asElement();
    // Past the 200 rows the engine's Load More reaches by itself
    await box.type('250');
    await box.press('Enter');
    for (let tries = 0; held.pages.length < 2 && tries < 200; tries += 1) await sleep(50);
    if (!held.data || held.pages.length < 2) return 'games: the jump sent no server pages';
    const body = await page.evaluate(
        url => fetch(url + '?smoke=1').then(response => response.text()),
        games + '/api/games/all/'
    );
    await held.data.respond({ status: 200, contentType: 'application/json', body });
    await page.waitForFunction(element => Alpine.$data(element).clientFilterReady, {}, filters);
    await page.evaluate(() => handleLoadMoreCSF(getClientSideFiltering()));
    for (const request of held.pages) await request.continue().catch(() => {});
    await sleep(800);
    const [start, end] = await page.evaluate(() => {
        const renderer = getClientSideFiltering().renderer;
        return [renderer.windowStart, renderer.windowEnd];
    });
    return start <= 249 && end > 249 ? null
        : `games: a server jump to 250 was dropped, the rows ${start + 1}-${end}`;
}

/**
 * A server Load More the engine's takeover overtook, on a link the takeover
 * rewrites (`?start=1990` gains its end), or whose request then fails. The
 * list is the same either way, so the engine answers the click: the key
 * that says so is the filter component's, not the URL's, and a failed page
 * is answered as a landed one. Answers as above.
 */
async function checkLoadMoreAcrossARewrittenTakeover(page, fails) {
    const engine = {
        site: games, data: '/api/games/all/',
        ready: element => Alpine.$data(element).clientFilterReady,
    };
    await page.setViewport({ width: 1440, height: 900 });
    const held = await holdEngineLoad(page, engine, request =>
        request.url().includes('append=true'));
    await page.goto(games + '/?start=1990', { waitUntil: 'load' });
    const decade = await page.waitForSelector('.year-grid-decade');
    const rows = '#game-list-container .game-row-wrapper';
    await sleep(1000);
    await page.click('.load-more-button');
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('acclaimed:need-csf')));
    const missing = await bothHeld(held, games);
    if (missing) return missing;
    const body = await page.evaluate(
        url => fetch(url + '?smoke=1').then(response => response.text()),
        games + engine.data
    );
    await held.data.respond({ status: 200, contentType: 'application/json', body });
    await page.waitForFunction(engine.ready, {}, decade);
    if (fails) {
        await held.server.respond({ status: 500, contentType: 'text/html', body: 'boom' });
    } else {
        await held.server.continue().catch(() => {});
    }
    await sleep(800);
    const count = await page.$$eval(rows, found => found.length);
    return count === 200 ? null
        : `games: an overtaken Load More${fails ? ' that failed' : ''} left ${count} rows on ${page.url()}`;
}

/**
 * A server Load More clicked on the list on the page while a filter change's
 * render was on its way: its key named the list asked for, so when the
 * engine took over and rendered that list the page was answered on it,
 * undoing the change's return to the top. Answers as above.
 */
async function checkLoadMoreBehindAFilterChange(page) {
    await page.setViewport({ width: 1440, height: 900 });
    const held = { data: null, render: null, page: null };
    await page.setRequestInterception(true);
    page.on('request', request => {
        const url = request.url();
        if (url.startsWith(games + '/api/games/all/') && !url.includes('smoke=1')) {
            held.data = request;
        } else if (url.includes('append=true')) {
            held.page = request;
        } else if (url.startsWith(games + '/?') &&
                ['xhr', 'fetch'].includes(request.resourceType())) {
            held.render = request;
        } else {
            request.continue();
        }
    });
    await page.goto(games + '/', { waitUntil: 'load' });
    const filters = await page.waitForSelector('[x-data*="filterComponent"]');
    await sleep(1000);
    await page.evaluate(element => Alpine.$data(element).updateSort('name'), filters);
    for (let tries = 0; !held.render && tries < 100; tries += 1) await sleep(50);
    if (!held.render) return 'games: the sort sent no server render';
    // Under the render's loading overlay, so not a mouse click
    await page.evaluate(() => document.querySelector('.load-more-button').click());
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('acclaimed:need-csf')));
    for (let tries = 0; !(held.page && held.data) && tries < 100; tries += 1) await sleep(50);
    if (!held.page) return 'games: the Load More click sent nothing';
    if (!held.data) return 'games: the engine asked for no data';
    const body = await page.evaluate(
        url => fetch(url + '?smoke=1').then(response => response.text()),
        games + '/api/games/all/'
    );
    await held.data.respond({ status: 200, contentType: 'application/json', body });
    await page.waitForFunction(element => Alpine.$data(element).clientFilterReady, {}, filters);
    await held.page.continue().catch(() => {});
    await held.render.continue().catch(() => {});
    await sleep(800);
    const end = await page.evaluate(() => getClientSideFiltering().renderer.windowEnd);
    return end === 100 ? null : `games: the old list's Load More extended the sorted one to ${end}`;
}

/**
 * The engine joins the page's rows to its payload's by position, so it keeps
 * only a copy of the version the page names: a fresher copy of another
 * version, kept five minutes without a check, repeated and dropped games
 * after an import. Answers as above.
 */
async function checkGamesDataFollowsThePage(page) {
    await page.setViewport({ width: 1440, height: 900 });
    const asked = [];
    page.on('request', request => {
        if (request.url().startsWith(games + '/api/games/')) asked.push(request.url());
    });
    await page.goto(games + '/', { waitUntil: 'networkidle2' });
    await startGamesEngine(page);
    const version = await page.evaluate(() => window.gameDataVersion);
    if (!version) return 'games: the page names no data version';
    if (!asked.some(url => url.endsWith('/api/games/all/?v=' + version))) {
        return `games: the engine asked for ${asked.join(', ') || 'nothing'}`;
    }
    // A copy stored a minute ago, of another version
    await page.evaluate(async () => {
        const cache = new GameDataCache();
        const stored = await cache._getCached();
        await cache._setCached('another-version', stored.data);
    });
    asked.length = 0;
    await page.goto(games + '/', { waitUntil: 'networkidle2' });
    await startGamesEngine(page);
    if (asked.length !== 1) return `games: a copy of another version was kept (${asked.length} requests)`;
    asked.length = 0;
    await page.goto(games + '/', { waitUntil: 'networkidle2' });
    await startGamesEngine(page);
    return asked.length === 0 ? null
        : `games: a copy of the page's own version was fetched again (${asked.join(', ')})`;
}

/**
 * A server Load More whose rows fail to go in: the button was left loading,
 * and disabled, for good. Answers as above.
 */
async function checkLoadMoreThatFailsToAppend(page) {
    await page.setViewport({ width: 1440, height: 900 });
    await page.goto(games + '/', { waitUntil: 'networkidle2' });
    await sleep(500);
    // Thrown once the rows are in: the button must still move past them,
    // or the next click asks for the same page and appends it twice
    await page.evaluate(() => {
        window.smokeProcess = htmx.process;
        htmx.process = () => { throw new Error('smoke: htmx.process failed'); };
    });
    await page.click('.load-more-button');
    await sleep(1500);
    const state = await page.$eval('.load-more-button',
        button => ({ loading: button.classList.contains('is-loading'), disabled: button.disabled }));
    if (state.loading || state.disabled) return 'a failed append left Load More stuck';
    await page.evaluate(() => { htmx.process = window.smokeProcess; });
    await page.click('.load-more-button');
    await sleep(1500);
    const ranks = await page.$$eval('#game-list-container .game-row.desktop [data-slot="rank"]',
        cells => cells.map(cell => cell.textContent.trim()));
    if (new Set(ranks).size !== ranks.length) {
        return `a retry after a failed append repeated rows (${ranks.length} rows, ` +
            `${new Set(ranks).size} ranks)`;
    }
    return ranks.length === 300 ? null : `${ranks.length} rows after two Load Mores, not 300`;
}

/**
 * A server Load More answered by a 200 that is not its page - a whole page,
 * say, from a proxy or a redirect: its rows went in, and with no meta to move
 * the button on, the button was left loading and disabled for good. Answers
 * as above.
 */
async function checkLoadMoreAnsweredByAnotherPage(page) {
    await page.setViewport({ width: 1440, height: 900 });
    let answered = false;
    await page.setRequestInterception(true);
    page.on('request', async request => {
        if (!answered && request.url().includes('append=true')) {
            answered = true;
            const body = await page.evaluate(
                url => fetch(url).then(response => response.text()), games + '/?sort=name');
            await request.respond({ status: 200, contentType: 'text/html', body });
        } else {
            request.continue();
        }
    });
    await page.goto(games + '/', { waitUntil: 'networkidle2' });
    await sleep(500);
    await page.click('.load-more-button');
    await sleep(1500);
    const rows = '#game-list-container .game-row.desktop [data-slot="rank"]';
    const count = await page.$$eval(rows, cells => cells.length);
    if (count !== 100) return `another page's answer to Load More appended ${count - 100} rows`;
    const state = await page.$eval('.load-more-button',
        button => ({ loading: button.classList.contains('is-loading'), disabled: button.disabled }));
    if (state.loading || state.disabled) return "another page's answer left Load More stuck";
    await page.click('.load-more-button');
    await sleep(1500);
    const ranks = await page.$$eval(rows, cells => cells.map(cell => cell.textContent.trim()));
    const expected = Array.from({ length: 200 }, (_, index) => String(index + 1));
    return ranks.join() === expected.join() ? null
        : `a retry after another page's answer gave ${ranks.length} rows, not 1-200`;
}

/**
 * Back before the engine, then a server Load More on the list still shown
 * while Back's render is on its way: the key already named Back's list, so
 * the engine answered the click on it. Answers as above.
 */
async function checkLoadMoreBehindBack(page) {
    await page.setViewport({ width: 1440, height: 900 });
    const held = { data: null, back: null, page: null };
    await page.setRequestInterception(true);
    page.on('request', request => {
        const url = request.url();
        if (url.startsWith(games + '/api/games/all/') && !url.includes('smoke=1')) {
            held.data = request;
        } else if (url.includes('append=true')) {
            held.page = request;
        } else if (url.startsWith(games + '/?') && !url.includes('sort=name') &&
                ['xhr', 'fetch'].includes(request.resourceType())) {
            held.back = request;
        } else {
            request.continue();
        }
    });
    await page.goto(games + '/', { waitUntil: 'load' });
    const filters = await page.waitForSelector('[x-data*="filterComponent"]');
    await sleep(1000);
    await page.evaluate(element => Alpine.$data(element).updateSort('name'), filters);
    await page.waitForFunction(() => location.search.includes('sort=name'));
    await sleep(500);
    await page.evaluate(() => history.back());
    for (let tries = 0; !held.back && tries < 100; tries += 1) await sleep(50);
    if (!held.back) return "games: Back sent no server render";
    // On the sorted list, still shown under Back's loading overlay
    await page.evaluate(() => document.querySelector('.load-more-button').click());
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('acclaimed:need-csf')));
    for (let tries = 0; !(held.page && held.data) && tries < 100; tries += 1) await sleep(50);
    if (!held.page) return 'games: the Load More click sent nothing';
    if (!held.data) return 'games: the engine asked for no data';
    const body = await page.evaluate(
        url => fetch(url + '?smoke=1').then(response => response.text()),
        games + '/api/games/all/'
    );
    await held.data.respond({ status: 200, contentType: 'application/json', body });
    await page.waitForFunction(element => Alpine.$data(element).clientFilterReady, {}, filters);
    await held.page.continue().catch(() => {});
    await held.back.continue().catch(() => {});
    await sleep(800);
    const end = await page.evaluate(() => getClientSideFiltering().renderer.windowEnd);
    return end === 100 ? null : `games: the sorted list's Load More extended Back's list to ${end}`;
}

/**
 * As above with no engine, the Load More's page landing before Back's render:
 * it was fetched from the address Back had moved to, so Back's list's rows
 * went in under the sorted one. The button names its own list now. Answers
 * as above.
 */
async function checkLoadMoreLandingBeforeBack(page) {
    await page.setViewport({ width: 1440, height: 900 });
    const held = { back: null, page: null };
    await page.setRequestInterception(true);
    page.on('request', request => {
        const url = request.url();
        if (url.startsWith(games + '/api/games/all/')) {
            // Never answered: the sort asks for the engine, which would
            // otherwise answer Back itself
        } else if (url.includes('append=true')) {
            held.page = request;
        } else if (url.startsWith(games + '/?') && !url.includes('sort=name') &&
                ['xhr', 'fetch'].includes(request.resourceType())) {
            held.back = request;
        } else {
            request.continue();
        }
    });
    await page.goto(games + '/', { waitUntil: 'load' });
    const filters = await page.waitForSelector('[x-data*="filterComponent"]');
    await sleep(1000);
    await page.evaluate(element => Alpine.$data(element).updateSort('name'), filters);
    await page.waitForFunction(() => location.search.includes('sort=name'));
    await sleep(500);
    const names = () => page.$$eval('#game-list-container .game-row.desktop [data-slot="name"]',
        cells => cells.map(cell => cell.textContent.trim()));
    const sorted = (await names()).slice(0, 100);
    await page.evaluate(() => history.back());
    for (let tries = 0; !held.back && tries < 100; tries += 1) await sleep(50);
    if (!held.back) return "games: Back sent no server render";
    // On the sorted list, still shown under Back's loading overlay
    await page.evaluate(() => document.querySelector('.load-more-button').click());
    for (let tries = 0; !held.page && tries < 100; tries += 1) await sleep(50);
    if (!held.page) return 'games: the Load More click sent nothing';
    const asked = held.page.url();
    await held.page.continue().catch(() => {});
    await sleep(800);
    const extended = await names();
    const byName = [...extended].sort((a, b) => a.localeCompare(b));
    await held.back.continue().catch(() => {});
    await sleep(800);
    const after = await names();
    if (!asked.includes('sort=name')) return `games: the sorted list's Load More asked for ${asked}`;
    if (extended.length !== 200 || extended.slice(0, 100).join() !== sorted.join() ||
            extended.join() !== byName.join()) {
        return `games: the sorted list's Load More gave ${extended.length} rows out of name order`;
    }
    return after.length === 100 ? null : `games: Back's render left ${after.length} rows`;
}

/**
 * A server Load More for rows 201-300, then a client jump that redrew the
 * button the page was on its way to: the page was dropped and the click went
 * unanswered, and the takeover's and the view toggle's answers started again
 * from 100 rows, giving 101-200. Answers as above.
 */
async function checkLoadMoreAcrossAClientJump(page) {
    const engine = {
        site: games, data: '/api/games/all/',
        ready: element => Alpine.$data(element).clientFilterReady,
    };
    await page.setViewport({ width: 1440, height: 900 });
    const held = await holdEngineLoad(page, engine, request =>
        request.url().includes('append=true') && request.url().includes('page=3'));
    await page.goto(games + '/', { waitUntil: 'load' });
    const component = await page.waitForSelector('[x-data*="filterComponent"]');
    const rows = '#game-list-container .game-row-wrapper';
    await sleep(1000);
    await page.click('.load-more-button');
    await page.waitForFunction(selector =>
        document.querySelectorAll(selector).length === 200, {}, rows);
    await sleep(300);
    await page.click('.load-more-button');
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('acclaimed:need-csf')));
    const missing = await bothHeld(held, games);
    if (missing) return missing;
    const body = await page.evaluate(
        url => fetch(url + '?smoke=1').then(response => response.text()),
        games + engine.data
    );
    await held.data.respond({ status: 200, contentType: 'application/json', body });
    await page.waitForFunction(engine.ready, {}, component);
    await page.evaluate(() => jumpToRankClientSide(getClientSideFiltering(), 50));
    await held.server.continue().catch(() => {});
    await sleep(800);
    const ids = await page.$$eval(rows, found => found.map(row => row.id));
    if (new Set(ids).size !== ids.length) return 'games: a row is shown twice';
    return ids.length === 300 ? null : `games: the click for rows 201-300 left ${ids.length} rows`;
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
    if (!await press(page, /^Clear All$/)) return 'games: no Clear All button after a jump';
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
 * engine does, or holds it until after. Landed, it used to append to the old
 * list and its out-of-band button replace the filter's; the filter request
 * now aborts it. Answers as above.
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
    const rows = '#album-list-container .media-row-wrapper';
    const before = await page.$$eval(rows, found => found.length);
    if (landed) {
        // Its request was aborted, so this answers nobody
        await held.server.continue().catch(() => {});
        await sleep(800);
        const next = await nextPage();
        if (!next || !next.includes('dir=desc')) {
            return `before the engine, the stale page left "${next}"`;
        }
    }
    await releaseAfterEngine(page, held, engine, decade);
    await sleep(800);
    const after = await page.$$eval(rows, found => found.length);
    if (after !== before) return `the takeover turned ${before} rows into ${after}`;
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
 * The same, for a search: a search box with focus as the engine took over
 * masked the query, for fear of rendering one half typed, so a search whose
 * own request had failed was never rendered and the box named a query the
 * list did not show. Answers as above.
 */
async function checkFailedSearchAcrossTheTakeover(page, text = 'album 11') {
    const engine = { site: music, data: '/api/all/', ready: musicReady };
    await page.setViewport({ width: 1440, height: 900 });
    const held = await holdEngineLoad(page, engine, request =>
        request.url().includes('q=album') &&
        ['xhr', 'fetch'].includes(request.resourceType()));
    await page.goto(music + '/', { waitUntil: 'load' });
    const decade = await page.waitForSelector('.year-grid-decade');
    await sleep(1000);
    await page.type('#album-filters input[name="q"]', text);
    const missing = await bothHeld(held, music);
    if (missing) return missing;
    await held.server.respond({ status: 500, contentType: 'text/html', body: 'boom' });
    await sleep(500);
    // The focus is still in the box
    await releaseAfterEngine(page, held, engine, decade);
    await sleep(500);
    const rows = await page.$$eval(albumRows, found => found.length);
    if (rows !== 11) return `after a failed search the list has ${rows} rows, not 11`;
    // Its commit was spent on the failed request, so the takeover pushes it
    return page.url().includes('q=album') ? null : `the failed search left the URL on ${page.url()}`;
}

/**
 * A failed search, then the reader typing on - a space before the next word
 * - as the engine arrives: the box no longer holds what failed, so it is a
 * search being typed, neither rendered nor pushed mid-word. Compared trimmed,
 * "album 11 " passed for the failed "album 11", and the takeover pushed it.
 * Answers as above.
 */
async function checkTypingOnAfterAFailedSearch(page) {
    const engine = { site: music, data: '/api/all/', ready: musicReady };
    await page.setViewport({ width: 1440, height: 900 });
    const held = await holdEngineLoad(page, engine, request =>
        request.url().includes('q=album') &&
        ['xhr', 'fetch'].includes(request.resourceType()));
    await page.goto(music + '/', { waitUntil: 'load' });
    const decade = await page.waitForSelector('.year-grid-decade');
    await sleep(1000);
    const box = '#album-filters input[name="q"]';
    await page.type(box, 'album 11');
    const missing = await bothHeld(held, music);
    if (missing) return missing;
    await held.server.respond({ status: 500, contentType: 'text/html', body: 'boom' });
    await sleep(500);
    // As the next keystroke leaves the box, without the event, so that no
    // commit of its own races the takeover; the focus stays in the box
    await page.$eval(box, input => { input.value += ' '; });
    const before = page.url();
    await releaseAfterEngine(page, held, engine, decade);
    await sleep(500);
    if (page.url() !== before) return `a half-typed search was pushed: ${page.url()}`;
    const rows = await page.$$eval(albumRows, found => found.length);
    return rows === 11 ? 'a half-typed search was rendered at the takeover' : null;
}

/**
 * An older failure of a request for the list's own filters, then a search
 * still being typed as the engine arrives: the failure once unmasked the
 * search, so the takeover took the typing for a form left ahead and
 * rendered the half-typed query. Answers as above.
 */
async function checkAnOlderFailureLeavesTheTypingAlone(page) {
    const engine = { site: music, data: '/api/all/', ready: musicReady };
    await page.setViewport({ width: 1440, height: 900 });
    const held = await holdEngineLoad(page, engine, request =>
        request.url().startsWith(music + '/?') && !request.url().includes('append=true') &&
        ['xhr', 'fetch'].includes(request.resourceType()));
    await page.goto(music + '/', { waitUntil: 'load' });
    const decade = await page.waitForSelector('.year-grid-decade');
    await sleep(1000);
    await page.evaluate(() => document.getElementById('album-filters').dispatchEvent(
        new CustomEvent('change', { bubbles: true, detail: {} })));
    const missing = await bothHeld(held, music);
    if (missing) return missing;
    await held.server.respond({ status: 500, contentType: 'text/html', body: 'boom' });
    await sleep(300);
    // Fetched first, so the engine arrives before the typing is committed
    const body = await page.evaluate(
        url => fetch(url + '?smoke=1').then(response => response.text()), music + engine.data
    );
    await page.type('#album-filters input[name="q"]', 'smo');
    await held.data.respond({ status: 200, contentType: 'application/json', body });
    await page.waitForFunction(engine.ready, {}, decade);
    // A render leaves the renderer owning the list; taking over without one
    // leaves it empty until the next interaction
    const rendered = await page.evaluate(
        () => getAlbumClientSideFiltering().renderer.currentItems.length
    );
    return rendered ? 'the takeover rendered the half-typed search' : null;
}

/**
 * With no engine, on `?start=1990`, a search sent by Enter that fails. The
 * form sends no end year where the controls hold one, so comparing them
 * with what was sent read the two spellings as a newer change, and the
 * sidebar was never rolled back. Answers as above.
 */
async function checkFailedEnterWithoutTheEngine(page) {
    await page.setViewport({ width: 1440, height: 900 });
    await page.setRequestInterception(true);
    page.on('request', request => {
        const url = request.url();
        if (url.startsWith(music + '/api/all/') || (url.startsWith(music + '/?') &&
                ['xhr', 'fetch'].includes(request.resourceType()))) {
            request.respond({ status: 500, contentType: 'text/plain', body: 'boom' });
        } else {
            request.continue();
        }
    });
    await page.goto(music + '/?start=1990', { waitUntil: 'networkidle2' });
    await sleep(500);
    const box = '#album-filters input[name="q"]';
    await page.type(box, 'zzz');
    await page.keyboard.press('Enter');
    await sleep(1500);
    const value = await page.$eval(box, input => input.value);
    const heading = await page.$eval('#search-title-text', title => title.textContent);
    if (value) return `the failed search stayed in the box as "${value}"`;
    return /zzz/.test(heading) ? `the heading kept the failed search: "${heading.trim()}"` : null;
}

/**
 * With no engine, a failed request while a search is still in its input
 * debounce: the roll-back reset the box under the reader's typing. Answers
 * as above.
 */
async function checkTypingBehindAFailureWithoutTheEngine(page) {
    await page.setViewport({ width: 1440, height: 900 });
    let first = null;
    await page.setRequestInterception(true);
    page.on('request', request => {
        const url = request.url();
        if (url.startsWith(music + '/api/all/')) {
            request.respond({ status: 500, contentType: 'text/plain', body: 'boom' });
        } else if (!first && url.includes('start=1990') &&
                ['xhr', 'fetch'].includes(request.resourceType())) {
            first = request;
        } else {
            request.continue();
        }
    });
    await page.goto(music + '/', { waitUntil: 'networkidle2' });
    await sleep(500);
    await (await page.waitForSelector('.year-grid-decade[title^="1990s:"]')).click();
    for (let tries = 0; !first && tries < 100; tries += 1) await sleep(50);
    if (!first) return 'the 1990s click sent no request';
    const box = '#album-filters input[name="q"]';
    await page.type(box, 'album');
    await first.respond({ status: 500, contentType: 'text/plain', body: 'boom' });
    await sleep(100);
    const value = await page.$eval(box, input => input.value);
    return value === 'album' ? null : `the roll-back left the search box on "${value}"`;
}

/**
 * And with no engine to come, the controls go back to the list: before, the
 * sidebar and the heading stayed on the decade the failed request asked for
 * while the list showed every year. `engineFirst` fails the engine's data
 * before the click, or after the click's request has failed. Answers as above.
 */
async function checkFailedRequestWithoutTheEngine(page, engineFirst) {
    await page.setViewport({ width: 1440, height: 900 });
    let data = null;
    await page.setRequestInterception(true);
    page.on('request', request => {
        const url = request.url();
        if (url.startsWith(music + '/api/all/') && !engineFirst) {
            data = request;
        } else if (url.startsWith(music + '/api/all/') ||
                (url.startsWith(music + '/?') &&
                    ['xhr', 'fetch'].includes(request.resourceType()))) {
            request.respond({ status: 500, contentType: 'text/plain', body: 'boom' });
        } else {
            request.continue();
        }
    });
    await page.goto(music + '/', { waitUntil: 'load' });
    const title = () => page.$eval('#search-title-text', element => element.textContent.trim());
    const heading = await title();
    const decade = await page.waitForSelector('.year-grid-decade[title^="1990s:"]');
    await sleep(1000);
    await decade.click();
    await sleep(1500);
    if (!engineFirst) {
        for (let tries = 0; !data && tries < 100; tries += 1) await sleep(50);
        if (!data) return 'the engine never asked for its data';
        await data.respond({ status: 500, contentType: 'text/plain', body: 'boom' });
        await sleep(500);
    }
    const start = await page.$eval('#album-filters [name="start"]', field => field.value);
    if (start) return `the form stayed on start=${start}`;
    const pressed = await page.$eval('.year-grid-decade[title^="1990s:"]',
        tile => tile.getAttribute('aria-pressed'));
    if (pressed !== 'false') return 'the year grid stayed on the 1990s';
    const now = await title();
    return now === heading ? null : `the heading read "${now}", not "${heading}"`;
}

/**
 * The same on games, which had no roll-back at all: a filter request that
 * failed with no engine to come left the year grid, the heading and the tab
 * on the decade asked for, over a list that still showed every year.
 * `engineFirst` fails the engine's data before the click's request fails,
 * or after it. With the data still on its way nothing is rolled back: the
 * engine, once it has it, renders the filters asked for. Answers as above.
 */
async function checkGamesFailedRequestWithoutTheEngine(page, engineFirst) {
    await page.setViewport({ width: 1440, height: 900 });
    let data = null;
    await page.setRequestInterception(true);
    page.on('request', request => {
        const url = request.url();
        if (url.startsWith(games + '/api/games/all/') && !engineFirst) {
            data = request;
        } else if (url.startsWith(games + '/api/games/all/') ||
                (url.startsWith(games + '/?') &&
                    ['xhr', 'fetch'].includes(request.resourceType()))) {
            request.respond({ status: 500, contentType: 'text/plain', body: 'boom' });
        } else {
            request.continue();
        }
    });
    await page.goto(games + '/', { waitUntil: 'load' });
    const title = () => page.$eval('#search-title', element => element.textContent.trim());
    const pressed = () => page.$eval('.year-grid-decade[title^="1990s:"]',
        tile => tile.getAttribute('aria-pressed'));
    const heading = await title();
    const tab = await page.title();
    const rows = await page.$$eval('#game-list-container .game-row.desktop', all => all.length);
    const decade = await page.waitForSelector('.year-grid-decade[title^="1990s:"]');
    await sleep(1000);
    await decade.click();
    await sleep(1500);
    if (!engineFirst) {
        for (let tries = 0; !data && tries < 100; tries += 1) await sleep(50);
        if (!data) return 'the engine never asked for its data';
        // Still to come, so the click is not given up yet
        if (await pressed() !== 'true') return 'the click was rolled back with the engine still to come';
        await data.respond({ status: 500, contentType: 'text/plain', body: 'boom' });
        await sleep(500);
    }
    if (await pressed() !== 'false') return 'the year grid stayed on the 1990s';
    const now = await title();
    if (now !== heading) return `the heading read "${now}", not "${heading}"`;
    if (await page.title() !== tab) return `the tab read "${await page.title()}", not "${tab}"`;
    if (new URL(page.url()).search) return `the address became ${page.url()}`;
    const left = await page.$$eval('#game-list-container .game-row.desktop', all => all.length);
    return left === rows ? null : `the list went from ${rows} rows to ${left}`;
}

/**
 * Back is not a control's change: the address has moved by the time its
 * render fails, so the controls stay with the address. Rolled back to the
 * list, they named the page Back had left, under an address that did not,
 * and the next change replaced that entry instead of pushing. Answers as
 * above.
 */
async function checkGamesFailedBackWithoutTheEngine(page) {
    await page.setViewport({ width: 1440, height: 900 });
    let failing = false;
    let refused = 0;
    await page.setRequestInterception(true);
    page.on('request', request => {
        const url = request.url();
        const render = url.startsWith(games + '/?') &&
            ['xhr', 'fetch'].includes(request.resourceType());
        if (url.startsWith(games + '/api/games/all/') || (render && failing)) {
            if (render) refused += 1;
            request.respond({ status: 500, contentType: 'text/plain', body: 'boom' });
        } else {
            request.continue();
        }
    });
    await page.goto(games + '/', { waitUntil: 'load' });
    const pressed = () => page.$eval('.year-grid-decade[title^="1990s:"]',
        tile => tile.getAttribute('aria-pressed'));
    const decade = await page.waitForSelector('.year-grid-decade[title^="1990s:"]');
    await sleep(1000);
    await decade.click();
    for (let tries = 0; tries < 60 && new URL(page.url()).pathname === '/'; tries += 1) {
        await sleep(100);
    }
    if (new URL(page.url()).pathname === '/') return 'the server never rendered the 1990s';
    failing = true;
    await page.goBack();
    await sleep(1500);
    const address = new URL(page.url());
    if (address.pathname !== '/' || address.search) return `Back went to ${page.url()}`;
    if (await pressed() !== 'false') {
        return 'the year grid named the 1990s under the address of every year';
    }
    // And a change that fails next is not put on that list either: its echo
    // is the 1990s, which the address no longer is
    const sent = refused;
    if (!sent) return 'the render Back asked for was never sent';
    const other = await page.waitForSelector('.year-grid-decade[title^="2000s:"]');
    await other.click();
    for (let tries = 0; tries < 60 && refused === sent; tries += 1) await sleep(50);
    if (refused === sent) return 'the second change was never sent';
    await sleep(800);
    return await pressed() === 'false'
        ? null : 'a second failure put the year grid on the 1990s, under the address of every year';
}

/**
 * The sidebar's search box by keyboard: the arrow keys move an active option
 * the field names (the WAI-ARIA combobox pattern), Enter follows it, and
 * Enter with none active is still the full search. Until 2026-11-10 the only
 * way from the field to a result was Tab. Answers as above.
 */
async function checkSearchBoxByKeyboard(page, site, query) {
    await page.setViewport({ width: 1440, height: 900 });
    await page.goto(site + '/', { waitUntil: 'load' });
    const field = await page.waitForSelector('#sidebar-search');
    const state = () => page.$eval('#sidebar-search', input => {
        const active = document.getElementById(input.getAttribute('aria-activedescendant') || '');
        const listbox = document.getElementById(input.getAttribute('aria-controls'));
        return {
            role: input.getAttribute('role'),
            expanded: input.getAttribute('aria-expanded'),
            listbox: listbox && listbox.getAttribute('role'),
            // Counted once they can be seen: Alpine shows the listbox a task
            // after it renders the options, and a key pressed in between
            // (which no hand is fast enough for) found them at no height
            options: listbox && listbox.getBoundingClientRect().height > 0
                ? listbox.querySelectorAll('[role="option"]').length : 0,
            selected: listbox ? listbox.querySelectorAll('[aria-selected="true"]').length : 0,
            active: active && {
                role: active.getAttribute('role'),
                selected: active.getAttribute('aria-selected'),
                href: active.href,
                visible: active.getBoundingClientRect().height > 0,
            },
            focused: document.activeElement === input,
        };
    });
    await sleep(500);
    let now = await state();
    if (now.role !== 'combobox' || now.listbox !== 'listbox') return `${site}: the field is no combobox with a listbox`;
    if (now.expanded !== 'false') return `${site}: the field says it is expanded before anything is typed`;
    await field.type(query);
    for (let tries = 0; tries < 60 && !(await state()).options; tries += 1) await sleep(100);
    now = await state();
    if (!now.options) return `${site}: a search for "${query}" showed no results`;
    if (now.expanded !== 'true') return `${site}: the field does not say its results are showing`;
    if (now.active) return `${site}: an option is active before an arrow key is pressed`;
    await page.keyboard.press('ArrowDown');
    const first = await state();
    if (!first.active || first.active.role !== 'option' || first.active.selected !== 'true') {
        return `${site}: ArrowDown named no selected option`;
    }
    if (!first.active.visible) return `${site}: the active option is not on screen`;
    if (first.selected !== 1) return `${site}: ${first.selected} options are selected`;
    if (!first.focused) return `${site}: the arrow key took the focus out of the field`;
    await page.keyboard.press('ArrowDown');
    const second = await state();
    if (!second.active || second.active.href === first.active.href) return `${site}: a second ArrowDown did not move on`;
    await page.keyboard.press('ArrowUp');
    await page.keyboard.press('ArrowUp');
    const wrapped = await state();
    if (!wrapped.active || wrapped.selected !== 1) return `${site}: ArrowUp past the top lost the active option`;
    if (wrapped.active.href === first.active.href) return `${site}: ArrowUp past the top did not wrap to the last option`;
    await page.keyboard.press('ArrowDown');
    await Promise.all([
        page.waitForNavigation({ waitUntil: 'load' }),
        page.keyboard.press('Enter'),
    ]);
    if (page.url() !== first.active.href) return `${site}: Enter went to ${page.url()}, not the active option's ${first.active.href}`;

    // And with no option active, Enter is what it was: the full search
    const again = await page.waitForSelector('#sidebar-search');
    await sleep(500);
    await again.type(query);
    for (let tries = 0; tries < 60 && !(await state()).options; tries += 1) await sleep(100);
    await page.keyboard.press('ArrowDown');
    // Typing forgets the active option at once: left to the search's 300 ms
    // debounce, Enter straight after a key followed the last query's option
    await page.keyboard.type('x');
    if ((await state()).active) return `${site}: an option stayed active while the query was being typed`;
    await page.keyboard.press('Backspace');
    await page.keyboard.press('Escape');
    now = await state();
    if (now.active || now.expanded !== 'false') return `${site}: Escape left the results open or an option active`;
    await Promise.all([
        page.waitForNavigation({ waitUntil: 'load' }),
        page.keyboard.press('Enter'),
    ]);
    const searched = new URL(page.url());
    return searched.searchParams.get('q') === query
        ? null : `${site}: Enter with no active option went to ${page.url()}`;
}

/**
 * allauth's own sign-up page is closed (it took any username), and its
 * route lands on the home page with the modal open on its sign-up screen:
 * allauth's login page links there, and a bare redirect home was a dead
 * end. Answers as above.
 */
async function checkSignupRouteOpensTheModal(page, site) {
    await page.setViewport({ width: 1440, height: 900 });
    await page.goto(site + '/accounts/signup/', { waitUntil: 'load' });
    for (let tries = 0; tries < 80; tries += 1) {
        const open = await page.evaluate(() => {
            const modal = document.getElementById('authModal');
            return Boolean(modal && modal.open &&
                modal.querySelector('input[name="password2"]'));
        });
        if (open) break;
        await sleep(100);
    }
    const state = await page.evaluate(() => {
        const modal = document.getElementById('authModal');
        return {
            path: location.pathname + location.search + location.hash,
            open: Boolean(modal && modal.open),
            form: Boolean(modal && modal.querySelector('input[name="password2"]')),
        };
    });
    if (state.path !== '/') return `${site}: /accounts/signup/ ended at ${state.path}`;
    if (!state.open) return `${site}: the sign-in modal did not open`;
    return state.form ? null : `${site}: the modal did not show the sign-up form`;
}

/**
 * A year range written backwards (by hand: no control writes one) is the
 * range. Each side listed nothing, under a heading reading "1999-1990". The
 * server's rows are compared with the forward range's, then the engine's once
 * it has taken over, which must add no history entry on the way. Answers as
 * above.
 */
async function checkAReversedYearRange(page, { site, rows, start }, [first, last]) {
    await page.setViewport({ width: 1440, height: 900 });
    const list = async () => ({
        ids: await page.$$eval(rows, found => found.map(row => row.id)),
        heading: await page.$eval('h1', heading => heading.textContent.trim()),
    });
    await page.goto(`${site}/?start=${first}&end=${last}`, { waitUntil: 'load' });
    const forward = await list();
    if (!forward.ids.length) return `${site}: ${first}-${last} lists nothing`;
    // Idle, as every check that starts the games engine waits: at `load`
    // Alpine may not have started the component that answers the start
    await page.goto(`${site}/?start=${last}&end=${first}`, { waitUntil: 'networkidle2' });
    const served = await list();
    if (served.ids.join() !== forward.ids.join()) {
        return `${site}: the server listed ${served.ids.length} rows for ${last}-${first}`;
    }
    if (served.heading !== forward.heading) return `${site}: headed "${served.heading}"`;
    const entries = await page.evaluate(() => history.length);
    await start(page);
    await sleep(800);
    const taken = await list();
    if (taken.ids.join() !== forward.ids.join()) {
        return `${site}: the engine listed ${taken.ids.length} rows for ${last}-${first}`;
    }
    if (taken.heading !== forward.heading) return `${site}: the engine headed "${taken.heading}"`;
    const added = await page.evaluate(() => history.length) - entries;
    return added ? `${site}: taking over added ${added} history entries` : null;
}

/**
 * Music's Load More before its engine has loaded is the server's: htmx
 * appends the rows and replaces the button's container out of band, and a
 * keyboard reader's focus, which was on the button, fell to the top of the
 * page. It goes to the new button, or at the end of the list to the
 * container, as the engine's own Load More leaves it. Answers as above.
 */
async function checkServerLoadMoreKeepsFocus(page) {
    await page.setViewport({ width: 1440, height: 900 });
    // The engine's data is held for good, so the server answers the button
    await holdEngineLoad(page, { site: music, data: '/api/all/' }, () => false);
    await page.goto(music + '/', { waitUntil: 'load' });
    await page.waitForSelector('.load-more-button');
    await sleep(1000);
    const before = await page.$$eval(albumRows, found => found.length);
    await page.focus('.load-more-button');
    await page.keyboard.press('Enter');
    await page.waitForFunction(
        (selector, count) => document.querySelectorAll(selector).length > count,
        {}, albumRows, before);
    await sleep(300);
    const focus = await page.evaluate(() => {
        const container = document.getElementById('load-more-container');
        const active = document.activeElement;
        return {
            inside: Boolean(container && active && container.contains(active)),
            where: active ? active.tagName + (active.id ? '#' + active.id : '') : 'nothing',
        };
    });
    return focus.inside ? null : `after a server Load More, focus was on ${focus.where}`;
}

/**
 * On an address the theme's cookie named a domain made of the address's last
 * two parts (".0.1"), which no browser keeps, so it was never written there.
 * A `theme` cookie already on 127.0.0.1, whose cookies every port shares,
 * could then never be changed, and decided every page: a reader who switched
 * to dark was put back on light by the next page. Answers as above.
 */
async function checkAThemeChosenOnAnAddressStays(page) {
    const address = `http://127.0.0.1:${port}`;
    const shown = () => page.evaluate(
        () => document.documentElement.getAttribute('data-theme'));
    await page.setViewport({ width: 1440, height: 900 });
    await page.emulateMediaFeatures([{ name: 'prefers-color-scheme', value: 'dark' }]);
    await page.goto(address + '/developers/', { waitUntil: 'load' });
    // As anything served on this address before could have left it
    await page.evaluate(() => { document.cookie = 'theme=lofi;path=/;max-age=600'; });
    await page.goto(address + '/developers/', { waitUntil: 'load' });
    if (await shown() !== 'lofi') return `127.0.0.1: the cookie's theme was not shown`;
    await page.evaluate(() => document.getElementById('theme-toggle').click());
    await sleep(300);
    if (await shown() !== 'forest') return '127.0.0.1: the toggle did not switch the theme';
    await page.goto(address + '/lists/', { waitUntil: 'load' });
    const next = await shown();
    return next === 'forest' ? null : `127.0.0.1: chose forest, and the next page showed ${next}`;
}

/**
 * Signs in as the reader `scripts/smoke_seed.py` makes, on `site`, through
 * the modal's own route. From a page that renders the CSRF token, which is
 * what sets its cookie.
 */
async function signIn(page, site) {
    await page.goto(site + '/', { waitUntil: 'load' });
    await page.waitForFunction(
        () => typeof readCsrfToken === 'function' && Boolean(readCsrfToken()));
    const answer = await page.evaluate(async () => {
        const response = await fetch('/auth/modal/login/', {
            method: 'POST',
            headers: { 'X-CSRFToken': readCsrfToken(), 'HX-Request': 'true' },
            body: new URLSearchParams({ login: 'smoke-reader', password: 'smoke-pass-1' }),
        });
        return response.status + (response.headers.get('HX-Redirect') ? '' : ', no redirect');
    });
    return answer === '200' ? null : `${site}: signing in answered ${answer}`;
}

/**
 * Each album row carries its listen button twice, for desktop and for
 * phones, and `media-tracking.js` copies a status chosen in one onto the
 * other. The artist page never loaded it: the hidden half kept its old icon
 * until a reload, and focus fell to the top of the page. Answers as above.
 */
async function checkArtistPageMirrorsAStatus(page) {
    await page.setViewport({ width: 1440, height: 900 });
    const refused = await signIn(page, music);
    if (refused) return refused;
    await page.goto(music + '/artists/smoke-band/', { waitUntil: 'load' });
    const wrapper = '[data-tracking-scope="album"]';
    await page.waitForSelector(wrapper);
    await page.waitForFunction(() => typeof readCsrfToken === 'function');
    await sleep(1000);
    const itemId = await page.$eval(wrapper, element => element.dataset.itemId);
    const both = `${wrapper}[data-item-id="${itemId}"]`;
    const twins = await page.$$eval(both, found => found.length);
    if (twins !== 2) return `the artist page has ${twins} buttons for one album`;
    // The visible half's own menu: a script's click opens it and another
    // picks (the keys are "music listen menu by keyboard")
    const pressed = await page.evaluate(selector => {
        const visible = [...document.querySelectorAll(selector)]
            .find(element => element.offsetParent !== null);
        const button = visible && visible.querySelector('.tracking-button');
        if (!button) return false;
        button.focus();
        button.click();
        return true;
    }, both);
    if (!pressed) return 'the artist page shows no listen button';
    await sleep(300);
    const chosen = await page.evaluate(selector => {
        const visible = [...document.querySelectorAll(selector)]
            .find(element => element.offsetParent !== null);
        const item = visible && visible.querySelector('[hx-post*="status=listened"]');
        if (!item) return false;
        item.focus();
        item.click();
        return true;
    }, both);
    if (!chosen) return 'the listen menu offers no Heard';
    await page.waitForFunction(selector =>
        [...document.querySelectorAll(selector)].some(e => e.dataset.status === 'listened'),
    {}, both);
    await sleep(500);
    const after = await page.evaluate(selector => ({
        statuses: [...document.querySelectorAll(selector)].map(e => e.dataset.status),
        focused: Boolean(document.activeElement &&
            document.activeElement.closest('[data-tracking-scope="album"]')),
    }), both);
    // Put back, so the check can run again on the same database
    await page.evaluate(async id => {
        await fetch(`/${id}/toggle-listened/?status=none`, {
            method: 'POST', headers: { 'X-CSRFToken': readCsrfToken() },
        });
    }, itemId);
    if (after.statuses.join() !== 'listened,listened') {
        return `the row's two buttons read ${after.statuses.join(' and ')}`;
    }
    return after.focused ? null : 'focus left the button after a status was chosen';
}

/**
 * A games reader's saved filters, through the page's own controls: the
 * Saved menu, the save and delete dialogs, and applying one. The markup is
 * the shared partials' (core/includes/_saved_filter*.html), which music had
 * and games took in place of its own copies; nothing ran games' before.
 * Answers as above.
 */
async function checkGamesSavedFilters(page) {
    await page.setViewport({ width: 1440, height: 900 });
    const refused = await signIn(page, games);
    if (refused) return refused;
    await page.goto(games + '/', { waitUntil: 'networkidle2' });
    await startGamesEngine(page);
    const sidebar = '#desktop-filter-sidebar';
    const clickText = (scope, text) => page.evaluate((scope, text) => {
        const button = [...document.querySelectorAll(scope + ' button')]
            .find(found => found.offsetParent !== null && found.textContent.trim() === text);
        if (button) button.click();
        return Boolean(button);
    }, scope, text);
    const names = () => page.evaluate(scope =>
        [...document.querySelectorAll(scope + ' ul.menu button.text-left')]
            .map(found => found.textContent.trim()), sidebar);
    const name = 'Smoke nineties';
    // Whatever an earlier run that stopped part way left behind
    await page.evaluate(async () => {
        const headers = { 'X-CSRFToken': readCsrfToken() };
        const kept = (await (await fetch('/api/saved-filters/')).json()).filter_sets || [];
        for (const filter of kept) {
            await fetch(`/api/saved-filters/${filter.id}/`, { method: 'DELETE', headers });
        }
    });

    // A filter to save: the 1990s, newest first
    const decade = await page.waitForSelector('.year-grid-decade[title^="1990s:"]');
    await decade.click();
    await sleep(600);
    const component = await page.$('[x-data*="filterComponent"]');
    await page.evaluate(element => Alpine.$data(element).updateSort('year'), component);
    await sleep(600);
    await page.evaluate(element => {
        const data = Alpine.$data(element);
        if ((data.filters.sortDirection || 'asc') !== 'desc') data.toggleSortDirection();
    }, component);
    await sleep(800);
    const saved = new URL(page.url()).search;

    if (!await clickText(sidebar, 'Saved')) return 'games shows no Saved button';
    await sleep(600);
    if (!await clickText(sidebar, 'Save current filters')) {
        return 'the Saved menu offers no "Save current filters" with a filter on';
    }
    // The dialog offers the heading as a name: type over it
    const field = await page.waitForSelector('#save-filter-name-input', { visible: true });
    await field.evaluate(input => { input.focus(); input.select(); });
    await field.type(name);
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => !document.querySelector('dialog[open]'));
    await sleep(500);

    // Start again from the unfiltered page, then apply it
    await page.goto(games + '/', { waitUntil: 'networkidle2' });
    await startGamesEngine(page);
    if (!await clickText(sidebar, 'Saved')) return 'games shows no Saved button after a reload';
    await page.waitForFunction(scope =>
        document.querySelector(scope + ' ul.menu button.text-left'), {}, sidebar);
    const listed = await names();
    if (!listed.includes(name)) return `the Saved menu lists ${listed.join(', ') || 'nothing'}`;
    await clickText(sidebar, name);
    await sleep(1000);
    const applied = new URL(page.url()).search;

    // Take it away again, so the check can run twice on one database
    if (!await clickText(sidebar, 'Saved')) return 'the Saved button went after applying';
    await sleep(500);
    const asked = await page.evaluate((scope, name) => {
        const button = document.querySelector(scope + ` button[aria-label="Delete ${name}"]`);
        if (button) button.click();
        return Boolean(button);
    }, sidebar, name);
    if (!asked) return 'the saved filter has no Delete button';
    await page.waitForSelector('dialog[open]');
    if (!await clickText('dialog[open]', 'Delete')) return 'the delete dialog has no Delete';
    await page.waitForFunction(() => !document.querySelector('dialog[open]'));
    await sleep(500);
    const left = await names();

    if (applied !== saved) return `saved ${saved} and applying it gave ${applied}`;
    if (!saved.includes('dir=desc')) return `the direction was not in what was saved: ${saved}`;
    return left.includes(name) ? `"${name}" was still listed after deleting it` : null;
}

/**
 * The listen button's dropdown is a menu: Enter opens it on its first item,
 * the arrows walk it and wrap, and Tab closes it and returns to the button.
 * ArrowUp on the closed button opens it on its last item, and an arrow in
 * the 75 ms a closed menu fades reopens it.
 * Its button said `aria-haspopup` and the list behind it had no role and
 * took no key (`media-tracking.js`). Real key presses, since the wiring is
 * Alpine's show, a capture-phase click and a document keydown together.
 * Answers as above.
 */
async function checkTrackingMenuByKeyboard(page) {
    await page.setViewport({ width: 1440, height: 900 });
    const refused = await signIn(page, music);
    if (refused) return refused;
    await page.goto(music + '/artists/smoke-band/', { waitUntil: 'load' });
    await page.waitForSelector('[data-tracking-scope="album"]');
    await page.waitForFunction(() => window.Alpine && window.MediaTracking);
    await sleep(1000);
    const where = () => page.evaluate(() => {
        const active = document.activeElement;
        const wrapper = active && active.closest('.tracking-button-wrapper');
        if (!wrapper) return 'outside';
        const items = [...wrapper.querySelectorAll('[role="menuitem"]')]
            .filter(item => item.offsetParent !== null);
        if (active.classList.contains('tracking-button')) {
            return 'button, ' + (items.length ? 'open' : 'closed');
        }
        return `item ${items.indexOf(active) + 1} of ${items.length}`;
    });
    const focused = await page.evaluate(() => {
        const button = [...document.querySelectorAll('.tracking-button')]
            .find(element => element.offsetParent !== null);
        if (button) button.focus();
        return Boolean(button);
    });
    if (!focused) return 'the artist page shows no listen button';
    const roles = await page.evaluate(() => {
        const wrapper = document.activeElement.closest('.tracking-button-wrapper');
        return [wrapper.querySelector('ul').getAttribute('role'),
            wrapper.querySelectorAll('[role="menuitem"]').length].join();
    });
    if (roles !== 'menu,3') return `the dropdown's roles read ${roles}`;
    const steps = [];
    for (const key of ['Enter', 'ArrowDown', 'ArrowUp', 'ArrowUp', 'End', 'Home', 'Tab']) {
        await page.keyboard.press(key);
        await sleep(250);
        steps.push(`${key}: ${await where()}`);
    }
    // An arrow on the closed button opens it too, and Escape hands focus back
    await page.keyboard.press('ArrowDown');
    await sleep(250);
    steps.push(`ArrowDown: ${await where()}`);
    await page.keyboard.press('Escape');
    await sleep(250);
    steps.push(`Escape: ${await where()}`);
    // ArrowUp opens it on its last item, as the menu button pattern has it
    await page.keyboard.press('ArrowUp');
    await sleep(250);
    steps.push(`ArrowUp: ${await where()}`);
    // A key in the 75 ms a closed menu takes to fade. Its items are still
    // laid out, so the arrow was read as if it were open: focus went to an
    // item, the item vanished, and focus fell out of the menu altogether.
    // The menu is closed from Escape on, and the arrow reopens it.
    await page.keyboard.press('Escape');
    await page.keyboard.press('ArrowDown');
    await sleep(250);
    steps.push(`Escape, ArrowDown: ${await where()}`);
    // And it is above the page: the closed menu's timer, which drops it back
    // among the rows 100 ms on, must not fire on the reopened one
    const raised = await page.evaluate(() => {
        const wrapper = document.activeElement.closest('.tracking-button-wrapper');
        return Boolean(wrapper) && wrapper.classList.contains('z-[9999]');
    });
    if (!raised) return 'a menu reopened as it faded was left under the page';
    await page.keyboard.press('Escape');
    await sleep(250);
    const expected = [
        'Enter: item 1 of 3', 'ArrowDown: item 2 of 3', 'ArrowUp: item 1 of 3',
        'ArrowUp: item 3 of 3', 'End: item 3 of 3', 'Home: item 1 of 3',
        'Tab: button, closed', 'ArrowDown: item 1 of 3', 'Escape: button, closed',
        'ArrowUp: item 3 of 3', 'Escape, ArrowDown: item 1 of 3',
    ];
    if (steps.join('; ') !== expected.join('; ')) {
        return `the listen menu by keyboard went ${steps.join('; ')}`;
    }

    // With a quick-mark mode on, a click on the button applies the picked
    // status and opens nothing. An arrow that opened the menu by clicking
    // marked the album, and the next press cleared it.
    await page.goto(music + '/', { waitUntil: 'load' });
    await page.waitForSelector('[data-quick-mark-scope="album"]');
    await page.waitForFunction(() => window.QuickMark && window.MediaTracking);
    await sleep(1000);
    await page.evaluate(() => window.QuickMark.set('album', 'listened'));
    let posts = 0;
    page.on('request', request => {
        if (request.method() === 'POST' && request.url().includes('toggle-listened')) posts += 1;
    });
    const before = await page.evaluate(() => {
        const button = [...document.querySelectorAll('.tracking-button')]
            .find(element => element.offsetParent !== null);
        button.focus();
        return button.closest('.tracking-button-wrapper').dataset.status;
    });
    await page.keyboard.press('ArrowDown');
    await sleep(600);
    const after = await where();
    await page.evaluate(() => window.QuickMark.set('album', ''));
    if (posts) return 'an arrow key on a listen button marked the album in quick-mark mode';
    return after === 'button, closed'
        ? null : `in quick-mark mode an arrow left focus at ${after} (the status was ${before})`;
}

/**
 * A Back whose render failed leaves the list it left under the address it
 * went to, and the engine, arriving then, found the filters equal to the
 * address's and took the rows for that address's list: it left the 1990s on
 * the unfiltered page, and Load More continued them with the whole ranking's
 * second page. It renders the address's list as it takes over, and writes no
 * history: the address is already right. Answers as above.
 */
async function checkGamesFailedBackThenTheEngine(page) {
    await page.setViewport({ width: 1440, height: 900 });
    let failing = false;
    let data = null;
    await page.setRequestInterception(true);
    page.on('request', request => {
        const url = request.url();
        const render = url.startsWith(games + '/?') &&
            ['xhr', 'fetch'].includes(request.resourceType());
        if (url.startsWith(games + '/api/games/all/') && !url.includes('smoke=1')) {
            data = request;
        } else if (render && failing) {
            request.respond({ status: 500, contentType: 'text/plain', body: 'boom' });
        } else {
            request.continue();
        }
    });
    await page.goto(games + '/', { waitUntil: 'load' });
    const rows = '#game-list-container .game-row-wrapper';
    const names = () => page.$$eval(rows + ' .game-row.desktop [data-slot="name"]',
        found => found.map(name => name.textContent.trim()));
    const every = await names();
    const decade = await page.waitForSelector('.year-grid-decade[title^="1990s:"]');
    await sleep(1000);
    await decade.click();
    for (let tries = 0; tries < 60 && new URL(page.url()).pathname === '/'; tries += 1) {
        await sleep(100);
    }
    if (new URL(page.url()).pathname === '/') return 'the server never rendered the 1990s';
    const nineties = await names();
    if (nineties.join() === every.join()) return 'the 1990s list is the whole ranking: nothing to tell apart';
    const entries = await page.evaluate(() => history.length);
    failing = true;
    await page.goBack();
    await sleep(1500);
    if (new URL(page.url()).pathname !== '/' || new URL(page.url()).search) {
        return `Back went to ${page.url()}`;
    }
    if ((await names()).join() !== nineties.join()) return 'the failed Back changed the list';
    for (let tries = 0; !data && tries < 100; tries += 1) await sleep(50);
    if (!data) return 'the engine never asked for its data';
    failing = false;
    const body = await page.evaluate(
        url => fetch(url + '?smoke=1').then(response => response.text()),
        games + '/api/games/all/'
    );
    await data.respond({ status: 200, contentType: 'application/json', body });
    await page.waitForFunction(element => Alpine.$data(element).clientFilterReady, {}, decade);
    await sleep(800);
    const shown = await names();
    if (shown.join() !== every.join()) {
        return `the engine took over on "${shown[0]}", not the unfiltered list's "${every[0]}"`;
    }
    if (new URL(page.url()).pathname !== '/' || new URL(page.url()).search) {
        return `the takeover moved the address to ${page.url()}`;
    }
    const now = await page.evaluate(() => history.length);
    if (now !== entries) return `the takeover left ${now} history entries, not ${entries}`;
    await page.click('.load-more-button');
    await sleep(800);
    const more = await names();
    if (more.length !== Math.min(200, every.length * 2) && more.length <= every.length) {
        return `Load More left ${more.length} rows`;
    }
    if (more.slice(0, every.length).join() !== every.join()) {
        return 'Load More did not continue the unfiltered list';
    }
    await page.goForward();
    await sleep(800);
    return new URL(page.url()).pathname === '/' && !new URL(page.url()).search
        ? 'Forward no longer reaches the 1990s' : null;
}

/**
 * And a search still being typed is left in its box when its request fails:
 * the roll-back emptied it, and the next keystrokes searched for the tail
 * of the word. Answers as above.
 */
async function checkGamesFailedSearchKeepsTheTyping(page) {
    await page.setViewport({ width: 1440, height: 900 });
    let failed = 0;
    await page.setRequestInterception(true);
    page.on('request', request => {
        const url = request.url();
        if (url.startsWith(games + '/api/games/all/') ||
                (url.startsWith(games + '/?') &&
                    ['xhr', 'fetch'].includes(request.resourceType()))) {
            if (!url.includes('/api/')) failed += 1;
            request.respond({ status: 500, contentType: 'text/plain', body: 'boom' });
        } else {
            request.continue();
        }
    });
    await page.goto(games + '/', { waitUntil: 'load' });
    const box = '#desktop-filter-sidebar [data-filter-search], [data-filter-search]';
    const input = await page.waitForSelector(box, { visible: true });
    await sleep(1000);
    await input.click();
    await page.keyboard.type('gam');
    for (let tries = 0; tries < 80 && !failed; tries += 1) await sleep(50);
    if (!failed) return 'the search was never sent';
    // Long enough for a text put back into the box to be read as a new
    // search, sent, failed and put back again, several times over
    await sleep(2500);
    const value = await input.evaluate(element => element.value);
    if (value !== 'gam') return `the search box was left on "${value}"`;
    return failed === 1 ? null : `the failed search was sent ${failed} times`;
}

/**
 * A request sent before Alpine starts, which fails while the engine's data
 * fails too: a row's genre (`how` 'genre') or Enter in the search box. The
 * controls start from the list the server rendered, so they read the
 * request they never saw as the reader having moved on, and left the form
 * ahead of the list. `engineFirst` fails the data before the click, or after
 * the request has failed. Answers as above.
 */
async function checkAFailureBeforeAlpine(page, how, engineFirst) {
    await page.setViewport({ width: 1440, height: 900 });
    const held = { alpine: null, data: null, sent: null };
    await page.setRequestInterception(true);
    page.on('request', request => {
        const url = request.url();
        if (url.includes('/vendor/alpine.min.js')) {
            held.alpine = request;
        } else if (url.startsWith(music + '/api/all/')) {
            if (engineFirst) {
                request.respond({ status: 500, contentType: 'text/plain', body: 'boom' });
            } else {
                held.data = request;
            }
        } else if (url.startsWith(music + '/?') &&
                ['xhr', 'fetch'].includes(request.resourceType())) {
            held.sent = url;
            request.respond({ status: 500, contentType: 'text/plain', body: 'boom' });
        } else {
            request.continue();
        }
    });
    await page.goto(music + '/', { waitUntil: 'domcontentloaded' });
    for (let tries = 0; !held.alpine && tries < 200; tries += 1) await sleep(50);
    if (!held.alpine) return 'Alpine was never asked for';
    if (!engineFirst) {
        for (let tries = 0; !held.data && tries < 200; tries += 1) await sleep(50);
        if (!held.data) return 'the engine never asked for its data';
    } else {
        await sleep(500);
    }
    const heading = await page.$eval('#search-title-text', element => element.textContent.trim());
    if (how === 'genre') {
        await page.evaluate(() => document.querySelector('#album-list-container [data-add-genre]').click());
    } else {
        await page.evaluate(() => {
            const box = document.querySelector('#album-filters input[name="q"]');
            box.value = 'zzz';
            box.form.requestSubmit();
        });
    }
    for (let tries = 0; !held.sent && tries < 100; tries += 1) await sleep(50);
    if (!held.sent) return `the ${how} sent no request before Alpine`;
    await sleep(300);
    if (!engineFirst) {
        await held.data.respond({ status: 500, contentType: 'text/plain', body: 'boom' });
        await sleep(300);
    }
    await held.alpine.continue();
    const decade = await page.waitForSelector('.year-grid-decade');
    await page.waitForFunction(element => Alpine.$data(element).initialized, {}, decade);
    await sleep(500);
    const form = await page.$eval('#album-filters', element => ({
        q: element.querySelector('[name="q"]').value,
        genres: element.querySelector('[name="genres"]').value,
    }));
    if (form.q || form.genres) {
        return `the form stayed ahead of the list: q="${form.q}", genres="${form.genres}"`;
    }
    const now = await page.$eval('#search-title-text', element => element.textContent.trim());
    return now === heading ? null : `the heading read "${now}", not "${heading}"`;
}

/**
 * With no engine, a failed request whose filters the controls spell another
 * way than the request did: a saved filter storing its years as strings, or
 * a hand-edited `?genres=` with junk in it. They read as the reader having
 * moved on, so the sidebar was never rolled back. Answers as above.
 */
async function checkAFailureSpelledAnotherWay(page, how) {
    await page.setViewport({ width: 1440, height: 900 });
    let genre = null;
    if (how === 'genres') {
        await page.goto(music + '/', { waitUntil: 'networkidle2' });
        genre = await page.$eval('#album-list-container [data-add-genre]',
            button => button.dataset.addGenre);
        // Or the engine starts from this visit's copy of its data
        await page.evaluate(() => sessionStorage.clear());
    }
    await page.setRequestInterception(true);
    page.on('request', request => {
        const url = request.url();
        if (url.startsWith(music + '/api/all/') || (url.startsWith(music + '/?') &&
                ['xhr', 'fetch'].includes(request.resourceType()))) {
            request.respond({ status: 500, contentType: 'text/plain', body: 'boom' });
        } else {
            request.continue();
        }
    });
    await page.goto(music + (genre ? `/?genres=${genre},abc` : '/'), { waitUntil: 'networkidle2' });
    const decade = await page.waitForSelector('.year-grid-decade');
    await page.waitForFunction(element => Alpine.$data(element).initialized, {}, decade);
    await sleep(500);
    const heading = await page.$eval('#search-title-text', element => element.textContent.trim());
    if (how === 'genres') {
        // Sent from the form as it stands, with no commit of the controls'
        // to send the genres again in their own spelling: as Enter does
        // before Alpine, or with a search the controls have not seen typed
        await page.evaluate(() => {
            const box = document.querySelector('#album-filters input[name="q"]');
            box.value = 'zzz';
            box.form.requestSubmit();
        });
    } else {
        await page.evaluate(element => Alpine.$data(element).applySavedFilter(
            { filters: { start: '1990', end: '1999' } }), decade);
    }
    await sleep(1500);
    const form = await page.$eval('#album-filters', element => ({
        q: element.querySelector('[name="q"]').value,
        start: element.querySelector('[name="start"]').value,
    }));
    if (form.q || form.start) {
        return `the form stayed ahead of the list: q="${form.q}", start="${form.start}"`;
    }
    const now = await page.$eval('#search-title-text', element => element.textContent.trim());
    return now === heading ? null : `the heading read "${now}", not "${heading}"`;
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
 * names the artist from the form's field, which only the engine's popstate
 * listener restored, so the heading rested on that listener running first:
 * it did when the engine loaded before Alpine, and not under load. The data
 * is held here until the controls are up, so their listener always comes
 * first. Answers as above.
 */
async function checkBackKeepsTheArtistInTheHeading(page) {
    await page.setViewport({ width: 1440, height: 900 });
    const held = await holdMusicData(page);
    await page.goto(music + '/?artists=smoke-band', { waitUntil: 'load' });
    const decade = await page.waitForSelector('.year-grid-decade');
    await page.waitForFunction(element => Alpine.$data(element).initialized, {}, decade);
    await held.release();
    if (!await press(page, /^Clear All$/)) return "no Clear All button on the artist's albums";
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
 * Back from a search or a sort on an entity page (artists, source lists,
 * developers). htmx restored its snapshot of the page, which held the DOM
 * Alpine built and threw an Alpine error per `x-for` clone; with none stored
 * it fetched the entry as a partial and swapped it in for the whole body.
 * It reloads now (base.html's htmx-config). And each page pushed an entry of
 * its own beside htmx's, so Back took two presses and the first reloaded
 * nothing. Answers as above.
 */
async function checkBackOnAnEntityPage(page, url, input, text, evict) {
    await page.setViewport({ width: 1440, height: 900 });
    const alpine = [];
    page.on('console', message => {
        if (/Alpine Expression Error/.test(message.text())) alpine.push(message.text());
    });
    await page.goto(url, { waitUntil: 'networkidle2' });
    const entries = await page.evaluate(() => history.length);
    await page.type(input, text);
    await page.waitForFunction(left => location.href !== left, {}, url);
    await sleep(800);
    const added = await page.evaluate(() => history.length) - entries;
    // Another tab's, saved before snapshots were turned off, under the key
    // htmx gives a path: no trailing slash
    const stale = '<p id="stale">stale</p>';
    if (evict) {
        await page.evaluate((content, path) => localStorage.setItem('htmx-history-cache',
            JSON.stringify([{ url: path.replace(/\/+$/, ''), content, title: 'stale', scroll: 0 }])),
        stale, new URL(url).pathname);
    }
    await page.evaluate(() => history.back());
    await sleep(1500);
    if (added !== 1) return `${url}: one search added ${added} history entries`;
    if (page.url() !== url) return `${url}: Back landed on ${page.url()}`;
    if (await page.$('#stale')) return `${url}: Back restored a stored snapshot`;
    if (!await page.$('.site-menu')) return `${url}: Back left a page with no sidebar`;
    return alpine.length ? `${url}: Back threw ${alpine.length} Alpine errors` : null;
}

/**
 * Answers the engine's data request, once `open()` is called, with the real
 * payload or with one of another version that lacks its first item: what an
 * import committing between the page and its payload hands the page. Keeps
 * the names of the items sent.
 */
async function servePayload(page, { site, data, items }, stale, reshape) {
    let open;
    const sent = { gate: new Promise(resolve => { open = resolve; }) };
    sent.open = open;
    await page.setRequestInterception(true);
    page.on('request', async request => {
        if (!request.url().startsWith(site + data) || request.url().includes('smoke=1')) {
            request.continue();
            return;
        }
        await sent.gate;
        const payload = JSON.parse(await page.evaluate(
            url => fetch(url + '?smoke=1').then(response => response.text()), site + data));
        const list = items(payload);
        if (stale) {
            payload.version = 'another-version';
            list.shift();
            if (reshape) reshape(list);
        }
        sent.names = list.map(item => item.n);
        await request.respond({
            status: 200, contentType: 'application/json', body: JSON.stringify(payload),
        });
    });
    return sent;
}

/**
 * The engine continues the page's rows by position, so a payload of another
 * version than the page's repeated and dropped rows on its first Load More
 * or jump. It renders the list from such a payload, at the rows the page
 * had; one of the page's own version leaves the page's rows alone. Answers
 * as above.
 */
async function checkEngineFollowsThePagesVersion(page, engine, path, stale, keep) {
    const { site, rows, names, start } = engine;
    await page.setViewport({ width: 1440, height: 900 });
    const sent = await servePayload(page, engine, stale, keep && (list => list.splice(keep)));
    await page.goto(site + path, { waitUntil: 'networkidle2' });
    await page.$eval(rows, row => { row.dataset.smokeServer = '1'; });
    sent.open();
    await start(page);
    await sleep(500);
    const kept = Boolean(await page.$(`${rows}[data-smoke-server]`));
    if (!stale) return kept ? null : `${site}${path}: the page's own version re-rendered its rows`;
    if (kept) return `${site}${path}: another version's payload took the page's rows over`;
    const shown = async () => {
        const window = await page.evaluate(csf => {
            const renderer = (csf === 'games' ? getClientSideFiltering() : getAlbumClientSideFiltering()).renderer;
            return [renderer.windowStart, renderer.windowEnd];
        }, site === games ? 'games' : 'music');
        const shownNames = await page.$$eval(names, cells => cells.map(cell => cell.textContent.trim()));
        if (!shownNames.length) return `${site}${path}: the render left no rows (window ${window.join('-')})`;
        const expected = sent.names.slice(...window);
        return shownNames.join() === expected.join() ? null
            : `${site}${path}: rows ${window.join('-')} showed ${shownNames[0]} to ` +
              `${shownNames[shownNames.length - 1]} (${shownNames.length}), not the payload's ` +
              `${expected[0]} to ${expected[expected.length - 1]}`;
    };
    const first = await shown();
    if (first || keep) return first;
    const button = path.includes('page=') ? '.load-previous-button' : '.load-more-button';
    if (!await page.$(button)) return `${site}${path}: no ${button} after the render`;
    await page.click(button);
    await sleep(800);
    return shown();
}

/**
 * A `?highlight=` link whose payload is of another version: the render
 * replaces the row the server scrolled to, and the new data can move the
 * album, here past the first page. A reader still where the link landed is
 * taken to the album, in a list or a grid; one who has moved on is left
 * there, with the album flashed in place. Answers as above.
 */
async function checkHighlightAcrossAnotherVersion(page, engine, { readerMoves, albumMoves, grid, early, stale = true, id = 5 }) {
    const path = `/?highlight=${id}`;
    await page.setViewport({ width: 1440, height: 900 });
    if (grid) {
        await page.evaluateOnNewDocument(() => localStorage.setItem('albumViewMode', 'grid'));
    }
    // Ranked last, past the first page: the engine orders by rank
    const sent = await servePayload(page, engine, stale, albumMoves && (list => {
        list.find(album => album.id === id).r = 1000;
    }));
    // Early: the data is there before the landing has scrolled
    if (early) sent.open();
    await page.goto(music + path, { waitUntil: 'networkidle2' });
    // Past the server row's own scroll
    if (!early) await sleep(600);
    if (readerMoves) {
        // As a scrollbar drag does, which in Firefox and Safari sends no
        // input event to listen for
        await page.evaluate(() => window.scrollBy(0, 3000));
        await sleep(500);
    }
    const before = await page.evaluate(() => window.scrollY);
    sent.open();
    await engine.start(page);
    // Past the landing's beat and a smooth scroll the length of the page
    await sleep(2500);
    const album = `#music-${id}${grid ? '-grid' : ''}`;
    const state = await page.evaluate(selector => {
        const element = document.querySelector(selector);
        if (!element) return null;
        const box = element.getBoundingClientRect();
        return {
            highlighted: Boolean(element.matches('.is-highlighted') ||
                element.querySelector('.is-highlighted')),
            inView: box.bottom > 0 && box.top < window.innerHeight,
            scrollY: window.scrollY,
        };
    }, album);
    const label = `music ${path}${grid ? ' (grid)' : ''}${early ? ' (early)' : ''}`;
    if (readerMoves) {
        const now = await page.evaluate(() => window.scrollY);
        if (Math.abs(now - before) > 5) {
            return `${label}: the render pulled a reader who had moved on from ${before} to ${now}`;
        }
        if (!state) return `${label}: the render left the album off the page`;
        return state.highlighted ? null : `${label}: the render lost the album's highlight`;
    }
    if (!state) return `${label}: the render left the album off the page`;
    if (!state.highlighted) return `${label}: the render lost the album's highlight`;
    return state.inView ? null : `${label}: the render left the album out of view`;
}

/** Whether a game's row half for this width is marked and on screen. */
const gameRowState = (page, id) => page.evaluate(gameId => {
    const desktop = window.matchMedia('(min-width: 962px)').matches;
    const element = document.getElementById(`game-${gameId}${desktop ? '' : '-mobile'}`);
    if (!element) return null;
    const box = element.getBoundingClientRect();
    return {
        highlighted: Boolean(element.matches('.is-highlighted') ||
            element.querySelector('.is-highlighted')),
        inView: box.bottom > 0 && box.top < window.innerHeight,
    };
}, id);

/**
 * A games `?highlight=` link lands on its game: the row is marked and
 * scrolled to, at either width, with the engine's data held back and then
 * let go, and for a game past the rows the server rendered, which only the
 * engine can reach. Music's landing has cases of its own; games' had none.
 * Answers as above.
 */
async function checkGamesHighlightLands(page, path, id, { width = 1440, hold = false } = {}) {
    await page.setViewport({ width, height: 900 });
    const sent = await servePayload(page, {
        site: games, data: '/api/games/all/', items: payload => payload.data.games,
    }, false);
    if (!hold) sent.open();
    await page.goto(games + path, { waitUntil: 'load' });
    const label = `games ${path} at ${width}px${hold ? ', data held' : ''}`;
    if (hold) {
        // Past the landing's own beat: the row is marked before the engine
        await sleep(1200);
        const early = await gameRowState(page, id);
        if (!early) return `${label}: the page has no row for the game`;
        if (!early.highlighted) return `${label}: no highlight before the engine`;
        sent.open();
    }
    // Past the landing's beat, a jump and a smooth scroll the length of a page
    let state = null;
    for (let tries = 0; tries < 40; tries += 1) {
        state = await gameRowState(page, id);
        if (state && state.highlighted && state.inView) break;
        await sleep(250);
    }
    // The page asks for its data whatever the landing needed of it: let the
    // answer go out before the page closes under it
    for (let tries = 0; tries < 100 && !sent.names; tries += 1) await sleep(50);
    await sleep(200);
    if (state && state.highlighted && state.inView) return null;
    if (!state) return `${label}: the game never reached the page`;
    if (!state.highlighted) return `${label}: the game was never highlighted`;
    return `${label}: the game was left out of view`;
}

/**
 * Two visitors land on one year's page for different games. The page is kept
 * whole for anonymous visitors whatever the highlight, so the second is
 * handed the first's copy: each must see their own game marked, and not the
 * other's. Answers as above.
 */
async function checkGamesHighlightFromAKeptPage(page) {
    // smoke_seed.py: games 5 and 40 are both of 1990
    const path = id => `/?start=1990&end=1990&highlight=${id}`;
    const landed = async (visitor, id) => {
        await visitor.setViewport({ width: 1440, height: 900 });
        await visitor.goto(games + path(id), { waitUntil: 'networkidle2' });
        for (let tries = 0; tries < 40; tries += 1) {
            const state = await gameRowState(visitor, id);
            if (state && state.highlighted) return true;
            await sleep(250);
        }
        return false;
    };
    if (!await landed(page, 5)) return `games ${path(5)}: the game was never highlighted`;
    const second = await page.browserContext().newPage();
    if (!await landed(second, 40)) return `games ${path(40)}: the game was never highlighted`;
    const other = await gameRowState(second, 5);
    if (!other) return `games ${path(40)}: the year's other game is not on the page`;
    return other.highlighted ? `games ${path(40)}: the last visitor's game is highlighted` : null;
}

/**
 * The CSV control asks for the list as filtered, and for nothing of where
 * the reader landed: it carried `highlight` and the whole year range, as a
 * link a scraper followed once per game. Answers as above.
 */
async function checkCsvButtonCarriesNoHighlight(page, site, path, wanted) {
    await page.setViewport({ width: 1440, height: 900 });
    let asked = null;
    await page.setRequestInterception(true);
    page.on('request', request => {
        const url = new URL(request.url());
        if (url.pathname !== '/download/') {
            request.continue();
            return;
        }
        asked = url;
        request.respond({
            status: 200, contentType: 'text/csv', body: 'rank\n',
            headers: { 'Content-Disposition': 'attachment; filename="smoke.csv"' },
        });
    });
    await page.goto(site + path, { waitUntil: 'networkidle2' });
    if (await page.$('a[href*="/download/"]')) return `${site}${path}: the CSV control is a link`;
    const button = await page.waitForSelector('button[data-download-url]', { visible: true });
    // The landing scrolls down to its row, and a click off screen hits nothing
    await sleep(1500);
    await button.evaluate(element => element.scrollIntoView({ block: 'center' }));
    await sleep(300);
    await button.click();
    for (let tries = 0; tries < 60 && !asked; tries += 1) await sleep(50);
    if (!asked) return `${site}${path}: the CSV button asked for nothing`;
    const query = asked.search.slice(1);
    return query === wanted ? null : `${site}${path}: the CSV button asked for ?${query}, not ?${wanted}`;
}

/**
 * A phone-width row opens by keyboard. The card went to its item on a click
 * anywhere and held no link, so Tab had nowhere to stop. Its title is a link
 * now, in the rows the server renders and in the ones the engine does.
 * Answers as above.
 */
async function checkMobileRowOpensByKeyboard(page, { site, cards, start }, detail) {
    // Every card's title links where the card goes, hidden halves included
    const unlinked = () => page.$$eval(cards, found => found.filter(card => {
        const link = card.querySelector('a[data-slot^="title-link"]');
        return !(link && link.getAttribute('href') === card.dataset.href);
    }).length);
    // The engine's rows first, at a width whose year grid can be clicked: a
    // decade is rendered from its data, both halves of each row
    await page.setViewport({ width: 1440, height: 900 });
    await page.goto(site + '/', { waitUntil: 'networkidle2' });
    await start(page);
    const before = await page.$$eval(cards, found => found.length);
    // Not clickDecade, which waits on music's address: games pushes
    // /games/1990s/ for the same click
    await (await page.waitForSelector('.year-grid-decade[title^="1990s:"]')).click();
    await page.waitForFunction(
        (selector, count) => document.querySelectorAll(selector).length !== count,
        {}, cards, before
    ).catch(() => {});
    await sleep(500);
    const after = await page.$$eval(cards, found => found.length);
    if (!after || after === before) return `${site}: the decade did not re-render the list (${before} rows, then ${after})`;
    if (await unlinked()) return `${site}: ${await unlinked()} of the engine's rows without a title link`;

    // Then the server's, at a phone's width, and Enter on the first
    await page.setViewport({ width: 420, height: 860 });
    await page.goto(site + '/', { waitUntil: 'networkidle2' });
    if (await unlinked()) return `${site}: ${await unlinked()} of the server's rows without a title link`;
    const link = await page.$(`${cards} a[data-slot^="title-link"]`);
    if (!link) return `${site}: no row with a title link`;
    const href = await link.evaluate(element => element.href);
    await link.focus();
    await Promise.all([
        page.waitForNavigation({ waitUntil: 'domcontentloaded' }),
        page.keyboard.press('Enter'),
    ]);
    if (page.url() !== href) return `${site}: Enter on a row went to ${page.url()}, not ${href}`;
    return detail.test(page.url()) ? null : `${site}: a row's link is ${href}`;
}

/** The text of each row an entity page lists, to tell them apart. */
const entityRows = (page, rows) =>
    page.$$eval(rows, found => found.map(row => row.textContent.replace(/\s+/g, ' ').trim()));

/**
 * An entity page's Load More (core/js/entity-load-more.js) answered by a 200
 * that is not its page: the inline copies it replaced appended the whole
 * page's rows and left the button loading and disabled for good. Answers as
 * above.
 */
async function checkEntityLoadMoreAnsweredByAnotherPage(page, { url, rows }) {
    await page.setViewport({ width: 1440, height: 900 });
    const alpine = [];
    page.on('console', message => {
        if (/Alpine Expression Error/.test(message.text())) alpine.push(message.text());
    });
    let answered = false;
    await page.setRequestInterception(true);
    page.on('request', async request => {
        if (!answered && request.url().includes('append=true')) {
            answered = true;
            const body = await page.evaluate(
                address => fetch(address).then(response => response.text()), url);
            await request.respond({ status: 200, contentType: 'text/html', body });
        } else {
            request.continue();
        }
    });
    await page.goto(url, { waitUntil: 'networkidle2' });
    const before = (await entityRows(page, rows)).length;
    await page.click('.load-more-button');
    await sleep(1000);
    const after = (await entityRows(page, rows)).length;
    if (after !== before) return `${url}: another page's answer appended ${after - before} rows`;
    const state = await page.$eval('.load-more-button',
        button => ({ loading: button.classList.contains('loading'), disabled: button.disabled }));
    if (state.loading || state.disabled) return `${url}: another page's answer left Load More stuck`;
    await page.click('.load-more-button');
    await sleep(1000);
    const listed = await entityRows(page, rows);
    if (listed.length <= before) return `${url}: a retry appended nothing`;
    if (new Set(listed).size !== listed.length) return `${url}: a retry repeated rows`;
    if (await page.$('.load-more-button')) return `${url}: the last page left Load More up`;
    return alpine.length ? `${url}: the new rows threw ${alpine.length} Alpine errors` : null;
}

/**
 * A Load More still on its way when a search swaps the list in: the inline
 * copies appended its rows under the search's. Answers as above.
 */
async function checkEntityLoadMoreBehindASearch(page, { url, rows, input, text }) {
    await page.setViewport({ width: 1440, height: 900 });
    let held = null;
    await page.setRequestInterception(true);
    page.on('request', request => {
        if (!held && request.url().includes('append=true')) {
            held = request;
        } else {
            request.continue();
        }
    });
    await page.goto(url, { waitUntil: 'networkidle2' });
    await page.click('.load-more-button');
    for (let tries = 0; !held && tries < 100; tries += 1) await sleep(50);
    if (!held) return `${url}: Load More sent no request`;
    await page.type(input, text);
    await page.waitForFunction(left => location.href !== left, {}, url);
    await sleep(800);
    const searched = await entityRows(page, rows);
    await held.continue();
    await sleep(1000);
    const after = await entityRows(page, rows);
    return after.length === searched.length ? null
        : `${url}: a Load More behind a search appended ${after.length - searched.length} rows`;
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
 * With no engine, a filter change queued behind a request that fails: htmx
 * sends the queued one from the form as it stands then, so the failure's
 * roll-back sent the old filters in its place. Answers as above.
 */
async function checkAChangeQueuedBehindAFailure(page, queued = true) {
    await page.setViewport({ width: 1440, height: 900 });
    let first = null;
    await page.setRequestInterception(true);
    page.on('request', request => {
        const url = request.url();
        if (url.startsWith(music + '/api/all/')) {
            request.respond({ status: 500, contentType: 'text/plain', body: 'boom' });
        } else if (!first && url.includes('start=1990') &&
                ['xhr', 'fetch'].includes(request.resourceType())) {
            first = request;
        } else {
            request.continue();
        }
    });
    await page.goto(music + '/', { waitUntil: 'networkidle2' });
    await sleep(500);
    await (await page.waitForSelector('.year-grid-decade[title^="1990s:"]')).click();
    for (let tries = 0; !first && tries < 100; tries += 1) await sleep(50);
    if (!first) return 'the 1990s click sent no request';
    await (await page.waitForSelector('.year-grid-decade[title^="2000s:"]')).click();
    // Queued behind the request, or still in the controls' 250 ms debounce
    if (queued) await sleep(800);
    await first.respond({ status: 500, contentType: 'text/plain', body: 'boom' });
    await page.waitForFunction(() => location.search.includes('start=2000'), { timeout: 5000 })
        .catch(() => {});
    const start = await page.$eval('#album-filters [name="start"]', field => field.value);
    if (start !== '2000') return `the queued 2000s click was sent as start="${start}"`;
    return page.url().includes('start=2000') ? null : `the list ended on ${page.url()}`;
}

/**
 * With no engine, a queued request that is sent, and fails, while a newer
 * click is still in the controls' debounce: htmx sends the queued one from
 * the form its commit wrote, but the controls once noted what they held as
 * it went out, which by then was the newer click, so the failure looked
 * like the reader's last word and its roll-back lost that click. Answers
 * as above.
 */
async function checkAClickBehindAQueuedFailure(page) {
    await page.setViewport({ width: 1440, height: 900 });
    let first = null;
    await page.setRequestInterception(true);
    page.on('request', request => {
        const url = request.url();
        const xhr = ['xhr', 'fetch'].includes(request.resourceType());
        if (url.startsWith(music + '/api/all/')) {
            request.respond({ status: 500, contentType: 'text/plain', body: 'boom' });
        } else if (!first && xhr && url.includes('start=1990')) {
            first = request;
        } else if (xhr && url.includes('start=2000')) {
            // The queued request, failing as soon as it is sent
            request.respond({ status: 500, contentType: 'text/plain', body: 'boom' });
        } else {
            request.continue();
        }
    });
    await page.goto(music + '/', { waitUntil: 'networkidle2' });
    await sleep(500);
    await (await page.waitForSelector('.year-grid-decade[title^="1990s:"]')).click();
    for (let tries = 0; !first && tries < 100; tries += 1) await sleep(50);
    if (!first) return 'the 1990s click sent no request';
    await (await page.waitForSelector('.year-grid-decade[title^="2000s:"]')).click();
    await sleep(800);
    // The 2000s request waits behind the 1990s one; the 2010s click is still
    // in its debounce when the 1990s one lands and lets the 2000s one go
    await (await page.waitForSelector('.year-grid-decade[title^="2010s:"]')).click();
    await first.continue();
    await page.waitForFunction(() => location.search.includes('start=2010'), { timeout: 5000 })
        .catch(() => {});
    const start = await page.$eval('#album-filters [name="start"]', field => field.value);
    if (start !== '2010') return `the 2010s click was lost: the form says start="${start}"`;
    return page.url().includes('start=2010') ? null : `the list ended on ${page.url()}`;
}

/**
 * With no engine, a genre clicked in a row while a decade click is still in
 * the controls' debounce, and the genre's request fails: it is sent without
 * a commit, so the decade is not in it, and the reader has moved on from it.
 * The controls once took what they held as it went out for what was sent,
 * and the roll-back lost the decade. Answers as above.
 */
async function checkARowGenreFailingBehindAClick(page) {
    await page.setViewport({ width: 1440, height: 900 });
    await page.setRequestInterception(true);
    let failed = false;
    page.on('request', request => {
        const url = request.url();
        const xhr = ['xhr', 'fetch'].includes(request.resourceType());
        if (url.startsWith(music + '/api/all/')) {
            request.respond({ status: 500, contentType: 'text/plain', body: 'boom' });
        } else if (!failed && xhr && /[?&]genres=\d/.test(url) && !/start=\d/.test(url)) {
            failed = true;
            request.respond({ status: 500, contentType: 'text/plain', body: 'boom' });
        } else {
            request.continue();
        }
    });
    await page.goto(music + '/', { waitUntil: 'networkidle2' });
    await sleep(500);
    await (await page.waitForSelector('.year-grid-decade[title^="1990s:"]')).click();
    const genre = await page.waitForSelector('#album-list-container [data-add-genre]');
    await genre.evaluate(element => element.scrollIntoView({ block: 'center' }));
    await genre.click();
    await page.waitForFunction(() => location.search.includes('start=1990'), { timeout: 5000 })
        .catch(() => {});
    if (!failed) return 'the genre click sent no request without the decade';
    const start = await page.$eval('#album-filters [name="start"]', field => field.value);
    if (start !== '1990') return `the 1990s click was lost: the form says start="${start}"`;
    return page.url().includes('start=1990') ? null : `the list ended on ${page.url()}`;
}

/**
 * A failed request for the filters the list already shows leaves nothing to
 * catch up on, so the takeover renders nothing: it once re-rendered, which
 * threw away the rows a server Load More had appended. Answers as above.
 */
async function checkAFailedRequestForTheListKeepsItsRows(page) {
    const engine = { site: music, data: '/api/all/', ready: musicReady };
    await page.setViewport({ width: 1440, height: 900 });
    const held = await holdEngineLoad(page, engine, request =>
        request.url().startsWith(music + '/?') && !request.url().includes('append=true') &&
        ['xhr', 'fetch'].includes(request.resourceType()));
    await page.goto(music + '/', { waitUntil: 'load' });
    const decade = await page.waitForSelector('.year-grid-decade');
    await sleep(1000);
    await page.click('.load-more-button');
    await page.waitForFunction(rows => document.querySelectorAll(rows).length === 120, {}, albumRows);
    // A request for the same filters, as commit() sends
    await page.evaluate(() => document.getElementById('album-filters').dispatchEvent(
        new CustomEvent('change', { bubbles: true, detail: {} })));
    const missing = await bothHeld(held, music);
    if (missing) return missing;
    await held.server.respond({ status: 500, contentType: 'text/html', body: 'boom' });
    await sleep(300);
    await releaseAfterEngine(page, held, engine, decade);
    await sleep(500);
    const rows = await page.$$eval(albumRows, found => found.length);
    return rows === 120 ? null : `the takeover turned 120 rows into ${rows}`;
}

/**
 * And a `?page=2` link whose takeover re-renders, for a filter request that
 * failed: the engine's rows start at #1, but the server's offset stayed on
 * the container for the next adoption to read. Answers as above.
 */
async function checkALaterPageForgetsItsStartOnceRendered(page) {
    const engine = { site: music, data: '/api/all/', ready: musicReady };
    await page.setViewport({ width: 1440, height: 900 });
    const held = await holdEngineLoad(page, engine, request =>
        request.url().includes('start=1990') &&
        ['xhr', 'fetch'].includes(request.resourceType()));
    await page.goto(music + '/?page=2', { waitUntil: 'load' });
    const decade = await page.waitForSelector('.year-grid-decade[title^="1990s:"]');
    await sleep(1000);
    await decade.click();
    const missing = await bothHeld(held, music);
    if (missing) return missing;
    await held.server.respond({ status: 500, contentType: 'text/html', body: 'boom' });
    await sleep(300);
    await releaseAfterEngine(page, held, engine, decade);
    await sleep(500);
    const state = await page.evaluate(() => ({
        attribute: Boolean(document.querySelector('[data-window-start]')),
        start: getAlbumClientSideFiltering().pageStart,
        windowStart: getAlbumClientSideFiltering().renderer.windowStart,
    }));
    if (state.windowStart !== 0) return `the 1990s list starts at row ${state.windowStart + 1}`;
    return state.attribute || state.start
        ? 'page 2\'s offset outlived the engine rendering from #1' : null;
}

/**
 * A `?page=2` link renders rows 101-120, and the engine took them for 1-20:
 * a jump to 110 appended rows already there, and one to 5 flashed row 105.
 * It starts the window where the page does. Answers as above.
 */
async function checkALaterPageStartsItsWindowThere(page) {
    await openMusicEngine(page, '/?page=2');
    const summary = await page.$eval('[data-result-count="desktop"]', line => line.textContent);
    if (!/101\D120 of 120/.test(summary)) return `page 2's count read "${summary.trim()}"`;
    if (!await page.$('.load-previous-button')) return 'page 2 had no Load Previous';
    const shown = () => page.$$eval(albumRows, found => found.map(row => row.id));
    const repeated = ids => new Set(ids).size !== ids.length;
    for (const position of [110, 5]) {
        await page.evaluate(at => getAlbumClientSideFiltering().jumpTo(at), position);
        await sleep(300);
        const ids = await shown();
        if (repeated(ids)) return `a jump to ${position} on page 2 repeated rows`;
        const rank = await page.evaluate(at => {
            const csf = getAlbumClientSideFiltering();
            const index = at - 1 - csf.renderer.windowStart;
            const row = document.querySelectorAll('#album-list-container .media-row-wrapper')[index];
            return row && row.querySelector('[data-slot="rank"]').textContent.trim();
        }, position);
        if (rank !== String(position)) {
            return `a jump to ${position} on page 2 found #${rank} in its place`;
        }
    }
    return null;
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
    if (!await press(page, /Filters/)) return `${site} has no Filters button to open the sheet`;
    await sleep(800);
    if (!await press(page, /^Range$/)) return `${site} has no Range button in the filter sheet`;
    await sleep(300);
    const shown = await page.evaluate(() => ['From year', 'To year'].map(
        name => document.querySelector(`select[aria-label="${name}"]`)
            .selectedOptions[0].textContent
    ));
    if (shown.join() !== '1900,1950') return `${site} From and To show ${shown}`;
    if (!await press(page, /^Clear All Filters$/)) {
        return `${site} has no Clear All Filters button on an empty result`;
    }
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
        // Only Clear All answers false, when there was no button to press
        if (await actions[step]() === false) {
            return `${site}${path}: no button for ${step}`;
        }
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
    const only = process.env.SMOKE_ONLY && new RegExp(process.env.SMOKE_ONLY);
    for (const [width, height] of only ? [] : [[1440, 900], [420, 860]]) {
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
                // The bottom sheet's contents are only rendered once opened.
                // Most pages have no sheet; one that should and does not
                // would otherwise pass with its contents never rendered
                const sheet = sheetPages.has(url);
                if (!await press(page, /Filters/) && sheet) {
                    problems.push('no Filters button to open the sheet');
                }
                await sleep(800);
                // And the year selects only once their mode is open
                for (const mode of [/^Year$/, /^Range$/]) {
                    if (!await press(page, mode) && sheet) {
                        problems.push(`no ${mode.source} button in the filter sheet`);
                    }
                    await sleep(300);
                }
            }
            // The chart's script is queued by the pages that show one, no
            // longer by every page: one that forgot would draw nothing, and
            // say nothing
            if (await page.evaluate(() => Boolean(document.querySelector('.rank-distribution')) &&
                typeof window.RankDistributionChart !== 'function')) {
                problems.push('a rank distribution chart with no script to draw it');
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
        if (only && !only.test(name)) return;
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
            // Asked for at `/`, though the address shown is /games/?...,
            // which only redirects there
            render: '/?',
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
    await report('games server jump overtaken by a filter', checkServerJumpOvertakenByAFilter);
    await report('games server jump overtaken by a filter and Back',
        page => checkServerJumpOvertakenByAFilter(page, true));
    await report('games Load More across a client jump', checkLoadMoreAcrossAClientJump);
    await report('games server jump across an engine Load More', checkServerJumpAcrossAnEngineLoadMore);
    await report('games Load More behind a filter change', checkLoadMoreBehindAFilterChange);
    await report('games Load More behind Back', checkLoadMoreBehindBack);
    await report('games Load More landing before Back', checkLoadMoreLandingBeforeBack);
    await report('games Load More that fails to append', checkLoadMoreThatFailsToAppend);
    await report('games Load More answered by another page', checkLoadMoreAnsweredByAnotherPage);
    await report("games data follows the page's version", checkGamesDataFollowsThePage);
    for (const fails of [false, true]) {
        await report(`games Load More across a rewritten takeover${fails ? ', failed' : ''}`,
            page => checkLoadMoreAcrossARewrittenTakeover(page, fails));
    }
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
    // title reads it from the form field the controls restore on Back
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
    await report('music failed search across the takeover', checkFailedSearchAcrossTheTakeover);
    // Sent as typed, read trimmed: the two once failed to match
    await report('music failed search with a trailing space',
        page => checkFailedSearchAcrossTheTakeover(page, 'album 11 '));
    await report('music typing on after a failed search', checkTypingOnAfterAFailedSearch);
    await report('music failed Enter on a link with no end year', checkFailedEnterWithoutTheEngine);
    await report('music an older failure leaves the typing alone', checkAnOlderFailureLeavesTheTypingAlone);
    await report('music typing behind a failure without the engine', checkTypingBehindAFailureWithoutTheEngine);
    for (const engineFirst of [true, false]) {
        await report(`music failed request, engine failed ${engineFirst ? 'first' : 'after'}`,
            page => checkFailedRequestWithoutTheEngine(page, engineFirst));
    }
    for (const engineFirst of [true, false]) {
        await report(`games failed request, engine failed ${engineFirst ? 'first' : 'after'}`,
            page => checkGamesFailedRequestWithoutTheEngine(page, engineFirst));
    }
    await report('games failed Back without the engine', checkGamesFailedBackWithoutTheEngine);
    await report('games failed Back, then the engine', checkGamesFailedBackThenTheEngine);
    await report('games a reversed year range', page => checkAReversedYearRange(page, {
        site: games, rows: engines.games.rows, start: startGamesEngine,
    }, [1990, 1999]));
    await report('music a reversed year range', page => checkAReversedYearRange(page, {
        site: music,
        rows: albumRows,
        start: async opened => opened.waitForFunction(
            musicReady, {}, await opened.waitForSelector('.year-grid-decade')),
    }, [1970, 1989]));
    await report('a theme chosen on 127.0.0.1 stays', checkAThemeChosenOnAnAddressStays);
    await report('music server Load More keeps focus', checkServerLoadMoreKeepsFocus);
    await report('music artist page mirrors a status', checkArtistPageMirrorsAStatus);
    await report('music listen menu by keyboard', checkTrackingMenuByKeyboard);
    await report('games saved filters', checkGamesSavedFilters);
    await report('games sign-up route opens the modal', page => checkSignupRouteOpensTheModal(page, games));
    await report('music sign-up route opens the modal', page => checkSignupRouteOpensTheModal(page, music));
    await report('games search box by keyboard', page => checkSearchBoxByKeyboard(page, games, 'smoke'));
    await report('music search box by keyboard', page => checkSearchBoxByKeyboard(page, music, 'smoke'));
    await report('games failed search keeps the typing', checkGamesFailedSearchKeepsTheTyping);
    for (const engineFirst of [true, false]) {
        await report(`music a row genre failing before Alpine, engine failed ${engineFirst ? 'first' : 'after'}`,
            page => checkAFailureBeforeAlpine(page, 'genre', engineFirst));
    }
    // Alpine puts the box back on the list as it starts, so this one passed
    // before; it guards the roll-back rule from the other side
    await report('music Enter failing before Alpine',
        page => checkAFailureBeforeAlpine(page, 'Enter', true));
    await report('music a failure under ?genres= with junk in it',
        page => checkAFailureSpelledAnotherWay(page, 'genres'));
    await report('music a failure from a saved filter with string years',
        page => checkAFailureSpelledAnotherWay(page, 'years'));
    await report('music Back onto an htmx entry', checkBackOntoAnHtmxEntry);
    await report('music Back before the engine', checkBackBeforeTheEngine);
    await report('music Back past an old snapshot', checkBackPastAnOldSnapshot);
    await report('music Back keeps the artist in the heading', checkBackKeepsTheArtistInTheHeading);
    await report('music typing across the takeover', checkTypingAcrossTheTakeover);
    await report('music server Load More adds no entry', checkServerLoadMoreAddsNoEntry);
    await report('music jump box waits for the engine', checkJumpBoxWaitsForTheEngine);
    await report('music jump box comes on', checkJumpBoxComesOn);
    await report('music page 2 starts its window there', checkALaterPageStartsItsWindowThere);
    await report('music page 2 forgets its start once rendered', checkALaterPageForgetsItsStartOnceRendered);
    await report('music a change queued behind a failure', checkAChangeQueuedBehindAFailure);
    await report('music a change still in the debounce behind a failure',
        page => checkAChangeQueuedBehindAFailure(page, false));
    await report('music a click behind a queued request that fails',
        checkAClickBehindAQueuedFailure);
    await report('music a row genre failing behind a click', checkARowGenreFailingBehindAClick);
    await report('music a failed request for the list itself keeps its rows',
        checkAFailedRequestForTheListKeepsItsRows);
    for (const [url, input, text] of [
        [music + '/artists/', '#artist-search', 'smo'],
        [music + '/lists/', '#music-list-search', 'smo'],
        [games + '/developers/', '#developer-search', 'nin'],
        [games + '/lists/', '#publication-search', 'smo'],
    ]) {
        for (const evict of [false, true]) {
            await report(`Back from a search on ${url}${evict ? ', a snapshot stored' : ''}`,
                page => checkBackOnAnEntityPage(page, url, input, text, evict));
        }
    }
    for (const entity of [
        { url: games + '/developers/', rows: '#developer-list-body .developer-row',
            input: '#developer-search', text: 'Smoke Studio 1' },
        { url: games + '/lists/', rows: '#publication-groups-container .publication-group',
            input: '#publication-search', text: 'Smoke Weekly 1' },
    ]) {
        await report(`${entity.url} Load More answered by another page`,
            page => checkEntityLoadMoreAnsweredByAnotherPage(page, entity));
        await report(`${entity.url} Load More behind a search`,
            page => checkEntityLoadMoreBehindASearch(page, entity));
    }
    const versioned = {
        games: { site: games, data: '/api/games/all/', items: payload => payload.data.games,
            rows: '#game-list-container .game-row-wrapper',
            names: '#game-list-container .game-row.desktop [data-slot="name"]',
            start: startGamesEngine },
        music: { site: music, data: '/api/all/', items: payload => payload.albums,
            rows: albumRows, names: '#album-list-container .media-row.desktop [data-slot="name"]',
            start: async page => page.waitForFunction(
                musicReady, {}, await page.waitForSelector('.year-grid-decade')) },
    };
    for (const [name, path] of [['games', '/'], ['music', '/'], ['music', '/?page=2']]) {
        for (const stale of [true, false]) {
            await report(`${name} ${path} engine with ${stale ? 'another' : 'the page\'s'} version`,
                page => checkEngineFollowsThePagesVersion(page, versioned[name], path, stale));
        }
    }
    // Shorter than the page's start: the top of the list, not an empty one
    await report('music /?page=2 engine with another, shorter version',
        page => checkEngineFollowsThePagesVersion(page, versioned.music, '/?page=2', true, 90));
    for (const [readerMoves, albumMoves, grid, early] of [
        [true, false, false, false], [false, false, false, false], [false, true, false, false],
        [false, true, true, false], [false, true, false, true],
    ]) {
        const name = [readerMoves && 'a reader who moved', albumMoves && 'an album that moved',
            grid && 'a grid', early && 'data before the landing'].filter(Boolean).join(', ') ||
            'a reader who stayed';
        await report(`music highlight across another version, ${name}`,
            page => checkHighlightAcrossAnotherVersion(
                page, versioned.music, { readerMoves, albumMoves, grid, early }));
    }
    // The page's own version, and an album past the rows the server rendered
    await report('music highlight past the first page',
        page => checkHighlightAcrossAnotherVersion(
            page, versioned.music, { stale: false, id: 110 }));
    // smoke_seed.py: game 5 is of 1990, and game 150 is past the first page
    for (const width of [1440, 420]) {
        for (const hold of [false, true]) {
            await report(`games highlight lands on its row, ${width}px${hold ? ', data held' : ''}`,
                page => checkGamesHighlightLands(
                    page, '/?start=1990&end=1990&highlight=5', 5, { width, hold }));
        }
    }
    await report('games highlight past the first page',
        page => checkGamesHighlightLands(page, '/?highlight=150', 150));
    await report('games mobile row opens by keyboard',
        page => checkMobileRowOpensByKeyboard(page, {
            site: games, cards: '#game-list-container .game-card-mobile', start: startGamesEngine,
        }, /\/game\/smoke-game-\d+\/$/));
    await report('music mobile row opens by keyboard',
        page => checkMobileRowOpensByKeyboard(page, {
            site: music, cards: '#album-list-container .media-card-mobile',
            start: async visitor => visitor.waitForFunction(
                musicReady, {}, await visitor.waitForSelector('.year-grid-decade')),
        }, /\/smoke-album-\d+\/$/));
    await report('games highlight from a kept page', checkGamesHighlightFromAKeptPage);
    await report('games CSV button carries no highlight',
        page => checkCsvButtonCarriesNoHighlight(
            page, games, '/?platforms=1&highlight=5', 'platforms=1'));
    await report('music CSV button carries no highlight',
        page => checkCsvButtonCarriesNoHighlight(
            page, music, '/?start=1970&end=1970&highlight=5', 'start=1970&end=1970'));
    await report('games empty range', page => checkRangeOutsideTheCorpus(page, games));
    await report('music empty range', page => checkRangeOutsideTheCorpus(page, music));
    await browser.close();
    process.exit(failures ? 1 : 0);
})().catch(error => {
    console.error(error);
    process.exit(1);
});
