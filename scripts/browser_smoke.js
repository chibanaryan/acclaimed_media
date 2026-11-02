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
 * that a year range the corpus does not reach shows and can be cleared, and
 * that the titles the engine writes are the ones the server renders.
 * SMOKE_ONLY_CHECKS=1 skips the page sweep and runs just those checks.
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
const pages = process.env.SMOKE_ONLY_CHECKS ? [] : [
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

/**
 * The tab title and the heading the engine writes after a filter change must
 * be the ones the server renders for the URL it pushed: the server picks the
 * keyword or the short title, and the two sides compose each separately.
 * Then Clear All must bring back the keyword title of the bare page. Answers
 * as above.
 */
async function checkTitlesMatchTheServer(page, { site, ready, heading }) {
    await page.setViewport({ width: 1440, height: 900 });
    await page.goto(site + '/', { waitUntil: 'networkidle2' });
    const bare = await page.title();
    const decade = await page.waitForSelector('.year-grid-decade[title^="1990s:"]');
    await decade.click();
    await page.waitForFunction(ready, { timeout: 15000 }, decade);
    // Music pushes /?start=1990&end=1999; games its landing page, /games/1990s/
    await page.waitForFunction(() => /start=1990|1990s/.test(location.href));
    await sleep(800);
    const compare = async () => page.evaluate(async selector => {
        const html = await (await fetch(location.href)).text();
        const server = new DOMParser().parseFromString(html, 'text/html');
        const text = doc => doc.querySelector(selector).textContent.trim();
        return {
            url: location.href,
            client: [document.title, text(document)],
            server: [server.title, text(server)],
        };
    }, heading);
    const filtered = await compare();
    if (filtered.client.join() !== filtered.server.join()) {
        return `${filtered.url}: the page says ${JSON.stringify(filtered.client)}, ` +
            `the server ${JSON.stringify(filtered.server)}`;
    }
    // A landing page keeps the keyword title, and a filtered URL is short
    const expected = location => (/\?/.test(location)
        ? /^1990s \| \w+ \| Acclaimed Media$/
        : /^Most Acclaimed .* of the 1990s \| Acclaimed Media$/);
    if (!expected(filtered.url).test(filtered.client[0])) {
        return `${filtered.url} is titled ${filtered.client[0]}`;
    }
    await press(page, /^Clear All( Filters)?$/);
    await page.waitForFunction(() => !/start=|1990s/.test(location.href));
    await sleep(800);
    const title = await page.title();
    return title === bare ? null : `Clear All left the tab titled ${title}, not ${bare}`;
}

/**
 * Back onto a landing page's path must give it the keyword title the server
 * renders there, not the short one a filtered URL gets. Answers as above.
 */
async function checkBackToALandingPageTitle(page) {
    await page.setViewport({ width: 1440, height: 900 });
    await page.goto(music + '/genres/smoke-rock/', { waitUntil: 'networkidle2' });
    const landing = await page.title();
    const decade = await page.waitForSelector('.year-grid-decade');
    await page.waitForFunction(
        element => Alpine.$data(element)._clientEngineReady(), {}, decade
    );
    await decade.click();
    await page.waitForFunction(() => /start=/.test(location.search));
    await sleep(800);
    await page.goBack();
    await page.waitForFunction(() => !location.search);
    await sleep(800);
    const title = await page.title();
    return title === landing ? null : `Back to the landing page titled it ${title}`;
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
            heading: '#search-title',
        },
        music: {
            site: music,
            data: '/api/all/',
            render: '/?',
            ready: element => Alpine.$data(element)._clientEngineReady(),
            loadMorePath: '/',
            rows: '#album-list-container .media-row-wrapper',
            heading: '#search-title-text',
        },
    };
    for (const [name, engine] of Object.entries(engines)) {
        await report(`${name} Back across the engine load`,
            page => checkBackAcrossEngineLoad(page, engine));
        await report(`${name} Load More across the engine load`,
            page => checkLoadMoreAcrossEngineLoad(page, engine));
        await report(`${name} titles match the server's`,
            page => checkTitlesMatchTheServer(page, engine));
    }
    for (const path of ['/?q=smoke', '/genres/smoke-rock/?utm_source=smoke']) {
        await report(`music keeps ${path}`,
            page => checkEngineLeavesTheUrlAlone(page, music + path));
    }
    await report('music search adds one entry', checkSearchAddsOneEntry);
    await report('music Back to a landing page title', checkBackToALandingPageTitle);
    await report('games empty range', page => checkRangeOutsideTheCorpus(page, games));
    await report('music empty range', page => checkRangeOutsideTheCorpus(page, music));
    await browser.close();
    process.exit(failures ? 1 : 0);
})().catch(error => {
    console.error(error);
    process.exit(1);
});
