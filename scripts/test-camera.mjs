#!/usr/bin/env node
/**
 * Browser lifecycle tests using an explicitly MOCKED YouTube player and image source.
 * No requests reach YouTube or a real camera; these tests do not verify live playback.
 * Requires Playwright and Chromium: CHROMIUM_PATH=/usr/bin/chromium node scripts/test-camera.mjs
 */
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {readFileSync, existsSync} from 'node:fs';
const require = createRequire(import.meta.url);
const {chromium} = require('playwright');
const moduleText = readFileSync(new URL('../static/camera.js', import.meta.url), 'utf8');
const css = readFileSync(new URL('../static/styles.css', import.meta.url), 'utf8');
const executablePath = process.env.CHROMIUM_PATH || ['/usr/bin/chromium', '/usr/bin/chromium-browser'].find(existsSync);
const browser = await chromium.launch({headless: true, ...(executablePath ? {executablePath} : {})});
let checks = 0;
const check = (actual, expected, label) => {assert.deepEqual(actual, expected, label); checks++;};
try {
  const context = await browser.newContext({viewport: {width: 1920, height: 1080}});
  let imageMode = 'success';
  let hungImage;
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.pathname === '/static/camera.js') return route.fulfill({contentType: 'text/javascript', body: moduleText});
    if (url.pathname === '/static/styles.css') return route.fulfill({contentType: 'text/css', body: css});
    if (url.pathname === '/fixture-image.png') {
      if (imageMode === 'hang') {
        // An unresolved test response exercises timeout recovery on later refreshes.
        hungImage = route;
        return;
      }
      return route.fulfill({contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="160" height="90"><text x="5" y="45">TEST FIXTURE</text></svg>'});
    }
    if (url.pathname === '/alternative') return route.fulfill({contentType: 'text/html', body: '<p>TEST ONLY: alternative player fixture</p>'});
    if (url.pathname.startsWith('/embed/')) return route.fulfill({contentType: 'text/html', body: '<p>TEST ONLY: mocked YouTube player</p>'});
    if (url.pathname === '/iframe_api') return route.abort('failed');
    if (url.pathname === '/') return route.fulfill({contentType: 'text/html', body: `<!doctype html><link rel="stylesheet" href="/static/styles.css"><style>.fixture-stage{position:relative;width:75vw;height:60vh}.camera-stage{height:100%;width:100%}</style><div class="fixture-stage"><div class="camera-stage" id="stage"><div class="camera-player" id="container"></div><div id="message"></div><button id="retry">Retry</button></div></div><span id="status"></span>`});
    throw new Error(`Unexpected test request: ${url.hostname}${url.pathname}`);
  });
  const page = await context.newPage();
  await page.clock.install();
  await page.goto('http://camera.test/');
  await page.evaluate(async () => {
    window.__created = 0;
    window.__destroyed = 0;
    window.__muted = 0;
    window.__played = 0;
    window.__players = [];
    window.YT = {
      PlayerState: {UNSTARTED: -1, ENDED: 0, PLAYING: 1, PAUSED: 2, BUFFERING: 3, CUED: 5},
      Player: class TestPlayer {
        constructor(target, options) {
          window.__created++;
          this.state = -1;
          this.position = 0;
          this.events = options.events;
          this.frame = document.createElement('iframe');
          this.frame.src = `https://www.youtube.com/embed/${options.videoId}?TEST_FIXTURE=1`;
          this.frame.width = '100%'; this.frame.height = '100%';
          target.replaceWith(this.frame);
          window.__players.push(this);
        }
        mute() {window.__muted++;}
        playVideo() {window.__played++;}
        destroy() {window.__destroyed++; this.frame.remove();}
        getIframe() {return this.frame;}
        getPlayerState() {return this.state;}
        getCurrentTime() {return this.position;}
      },
    };
    const {CameraPlayer} = await import('/static/camera.js');
    window.__camera = new CameraPlayer({container: document.querySelector('#container'), status: document.querySelector('#status'), message: document.querySelector('#message'), retry: document.querySelector('#retry')});
    new MutationObserver(() => {
      const state = document.querySelector('#status').dataset.state;
      document.querySelector('#stage').classList.toggle('is-playing', state === 'live' || state === 'image');
      document.querySelector('#stage').classList.toggle('is-embedded', state === 'embedded');
    }).observe(document.querySelector('#status'), {attributes: true, attributeFilter: ['data-state']});
    window.__source = {provider: 'youtube', url: 'https://www.youtube.com/embed/UqrwUKSkMEE', video_id: 'UqrwUKSkMEE', retry_seconds: 30};
    window.__camera.update(window.__source);
  });
  check(await page.locator('#status').textContent(), 'CONNECTING', 'Do not claim LIVE before PLAYING');
  await page.evaluate(() => {const player = window.__players.at(-1); player.events.onReady({target: player});});
  check(await page.evaluate(() => [window.__muted, window.__played]), [1, 1], 'Supported player is muted before autoplay');
  for (const viewport of [{width: 1920, height: 1080}, {width: 1280, height: 720}]) {
    await page.setViewportSize(viewport);
    await page.waitForFunction(() => {
      const frame = document.querySelector('#container iframe').getBoundingClientRect();
      const container = document.querySelector('#container').getBoundingClientRect();
      return Math.abs(frame.width / frame.height - 16 / 9) < .01 && frame.width <= container.width + 1 && frame.height <= container.height + 1;
    }, null, {polling: 25});
    const dimensions = await page.evaluate(() => {
      const frame = document.querySelector('#container iframe').getBoundingClientRect();
      const container = document.querySelector('#container').getBoundingClientRect();
      return {ratio: frame.width / frame.height, fits: frame.width <= container.width + 1 && frame.height <= container.height + 1};
    });
    check(Math.abs(dimensions.ratio - 16 / 9) < .01 && dimensions.fits, true, `Player preserves 16:9 and fits ${viewport.width}×${viewport.height}`);
  }
  await page.evaluate(() => {const player = window.__players.at(-1); player.state = 1; player.events.onStateChange({data: 1});});
  check(await page.locator('#status').getAttribute('data-state'), 'live', 'PLAYING sets LIVE');
  check(await page.locator('#stage').evaluate(el => el.classList.contains('is-playing')), true, 'Parent stage observer sees PLAYING');
  await page.evaluate(() => window.__camera.update(window.__source));
  check(await page.evaluate(() => window.__created), 1, 'Unchanged source does not reload the player');
  await page.evaluate(() => {const player = window.__players.at(-1); player.state = 3; player.events.onStateChange({data: 3});});
  check(await page.locator('#status').textContent(), 'BUFFERING', 'BUFFERING removes LIVE');
  await page.evaluate(() => window.__players.at(-1).events.onError({data: 100}));
  check(await page.locator('#status').getAttribute('data-state'), 'unavailable', 'Provider error removes LIVE');
  check(await page.locator('#retry').isVisible(), true, 'Unavailable camera exposes manual retry');
  await page.clock.runFor(15000);
  await page.evaluate(() => window.__players.at(-1).events.onError({data: 100}));
  await page.clock.runFor(15100);
  check(await page.evaluate(() => window.__created), 2, 'Repeated errors do not postpone scheduled camera retry');
  await page.evaluate(() => window.__players[0].events.onStateChange({data: 1}));
  check(await page.locator('#status').textContent(), 'CONNECTING', 'An old player cannot claim LIVE after replacement');
  await page.evaluate(() => {const player = window.__players.at(-1); player.events.onReady({target: player}); player.state = 1; player.events.onStateChange({data: 1});});
  check(await page.locator('#status').getAttribute('data-state'), 'live', 'Replacement player can recover');
  await page.clock.runFor(60100);
  check(await page.locator('#status').getAttribute('data-state'), 'unavailable', 'A PLAYING player with frozen media time is detected as stalled');
  await page.evaluate(() => window.__camera.update({...window.__source, alternative_url: 'http://camera.test/alternative', alternative_provider: 'iframe'}));
  await page.evaluate(() => window.__players.at(-1).events.onError({data: 100}));
  await page.clock.runFor(30100);
  await page.locator('#status[data-state="embedded"]').waitFor();
  check(await page.evaluate(() => window.__camera.usingAlternative), true, 'Playback failure automatically selects the configured alternative');
  check(await page.locator('#status').textContent(), 'CAMERA', 'Generic iframe never asserts LIVE');
  check(await page.locator('#stage').evaluate(el => el.classList.contains('is-embedded')), true, 'Parent observer sees embedded-camera state');
  await page.evaluate(() => window.__camera.update({provider: 'image', url: 'http://camera.test/fixture-image.png', image_refresh_seconds: 15}));
  await page.locator('#status[data-state="image"]').waitFor();
  check(await page.locator('#status').textContent(), 'REFRESHED IMAGE', 'Image fallback is explicitly labeled');
  check((await page.locator('#status').getAttribute('title')).includes('Image successfully loaded at'), true, 'Image records successful load time');
  imageMode = 'hang';
  await page.clock.runFor(15000);
  // Wait for Chromium to issue the image request before advancing its timeout.
  for (let attempts = 0; attempts < 50 && !hungImage; attempts++) await page.waitForTimeout(10);
  check(Boolean(hungImage), true, 'Later image refresh request started');
  await page.clock.runFor(30100);
  check(await page.locator('#status').getAttribute('data-state'), 'unavailable', 'A later hanging image refresh is marked unavailable');
  await hungImage.abort();
  await page.evaluate(() => window.__camera.update({provider: 'disabled'}));
  check(await page.locator('#status').textContent(), 'OFFLINE', 'Disabled camera does not assert playback');
  await page.evaluate(() => {delete window.YT; window.__camera.update(window.__source);});
  await page.locator('#status[data-state="unavailable"]').waitFor();
  check((await page.locator('#message').textContent()).includes('Camera unavailable'), true, 'Blocked provider API produces clean unavailable state');
  await page.evaluate(() => window.__camera.destroy());
  await page.clock.runFor(301000);
  check(await page.locator('#container').innerHTML(), '', 'Destroy removes player and cancels retries');
  const eventsAfterDestroy = await page.evaluate(() => window.__created);
  await page.clock.runFor(301000);
  check(await page.evaluate(() => window.__created), eventsAfterDestroy, 'Destroyed player does not restart');
  await context.close();
  console.log(`Camera browser tests: ${checks} checks passed (explicit mock player/image fixtures; live playback unverified).`);
} finally {
  await browser.close();
}
