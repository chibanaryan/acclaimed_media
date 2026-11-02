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
 * that a games jump filters once and Clear All after it adds no history
 * entry, and that a year range the corpus does not reach shows and can be
 * cleared.
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

/**
 * The debounced commit and the typing timer both answer one search, so each
 * search left two identical entries and Back needed two presses. Answers as
 * above.
 */
async function checkSearchAddsOneEntry(page) {
    await page.setViewport({ width: 1440, height: 900 });
    await page.goto(music + '/', { waitUntil: 'networkidle2' });
    const decade = await page.waitForSelector('.year-grid-decade');
    await page.waitForFunction(
        element => Alpine.$data(element)._clientEngineReady(), {}, decade
    );
    const entries = await page.evaluate(() => history.length);
    await page.type('#album-filters input[name="q"]', 'smoke');
    await sleep(1200);
    const added = await page.evaluate(() => history.length) - entries;
    return added === 1 ? null : `one search added ${added} history entries`;
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
            ready: element => Alpine.$data(element)._clientEngineReady(),
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
    for (const path of ['/?q=smoke', '/genres/smoke-rock/?utm_source=smoke']) {
        await report(`music keeps ${path}`,
            page => checkEngineLeavesTheUrlAlone(page, music + path));
    }
    await report('music search adds one entry', checkSearchAddsOneEntry);
    await report('games empty range', page => checkRangeOutsideTheCorpus(page, games));
    await report('music empty range', page => checkRangeOutsideTheCorpus(page, music));
    await browser.close();
    process.exit(failures ? 1 : 0);
})().catch(error => {
    console.error(error);
    process.exit(1);
});
