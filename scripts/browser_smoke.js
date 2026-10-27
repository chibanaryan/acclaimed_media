/**
 * Browser smoke test: loads the main pages in Chrome at desktop and phone
 * widths, opens the mobile filter sheet, and fails on any uncaught error,
 * Alpine expression error or Content-Security-Policy violation.
 *
 *   node scripts/browser_smoke.js http://127.0.0.1:8000
 *
 * Needs puppeteer-core and Chrome (CHROME_PATH, or the usual install path).
 * CI's `browser` job runs it against `runserver` on scripts/smoke_seed.py's
 * data. These are the failures no Python test sees: a template binding that
 * only throws in the browser, or an inline script the CSP would refuse.
 */
const puppeteer = require('puppeteer-core');

const base = process.argv[2] || 'http://127.0.0.1:8000';
const chrome = process.env.CHROME_PATH ||
    (process.platform === 'darwin'
        ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
        : '/usr/bin/google-chrome');
const pages = [
    '/', '/games/1990s/', '/game/smoke-game-1/', '/developers/',
    '/developers/?sort=name', '/developers/nintendo/', '/lists/', '/blog/',
    '/no-such-page/', '/music/', '/music/artists/', '/music/lists/',
];

(async () => {
    const browser = await puppeteer.launch({ executablePath: chrome, headless: true, args: ['--no-sandbox'] });
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
            await page.goto(base + url, { waitUntil: 'networkidle2' });
            await new Promise(resolve => setTimeout(resolve, 1000));
            if (width < 962) {
                // The bottom sheet's contents are only rendered once opened
                await page.evaluate(() => {
                    const button = [...document.querySelectorAll('button')]
                        .find(b => b.offsetParent && /Filters/.test(b.textContent));
                    if (button) button.click();
                });
                await new Promise(resolve => setTimeout(resolve, 800));
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
    await browser.close();
    process.exit(failures ? 1 : 0);
})().catch(error => {
    console.error(error);
    process.exit(1);
});
