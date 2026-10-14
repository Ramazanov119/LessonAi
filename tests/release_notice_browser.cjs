/* Offline browser checks. Set LESSONAI_PLAYWRIGHT_PATH to a test-only playwright-core install.
   Start tests/qa_release_app.py on port 8765 first; no AI or Supabase connections. */
const assert = require('node:assert/strict');
const { chromium } = require(process.env.LESSONAI_PLAYWRIGHT_PATH || 'playwright-core');
const baseURL = (process.env.LESSONAI_QA_URL || 'http://127.0.0.1:8765') + '?qa_release_id=browser_run_' + Date.now();
let passed = 0;
async function check(name, action) {
  await action(); passed += 1; console.log('PASS', name);
}
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.LESSONAI_CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true,
  });
  try {
    const context = await browser.newContext({viewport: {width: 1280, height: 900}});
    const page = await context.newPage();
    await page.goto(baseURL);
    const frame = page.frameLocator('iframe').first();
    const notice = frame.locator('#notice');
    await notice.waitFor({state: 'visible', timeout: 20000});
    const appeared = Date.now();
    await check('notice visible; form remains interactive on first home visit', async () => {
      assert.equal(await frame.locator('#title').textContent(), 'LessonAI обновлён!');
      await page.getByRole('textbox', {name: 'Interactive field'}).fill('test while notice is visible');
      await page.getByRole('textbox', {name: 'Interactive field'}).press('Tab');
      await page.getByText('Mock generations: 0', {exact: true}).waitFor();
      await notice.waitFor({state: 'visible'});
    });
    await check('actual notification disappears after 15 seconds, despite rerun', async () => {
      await notice.waitFor({state: 'hidden', timeout: 20000});
      const elapsed = Date.now() - appeared;
      assert(elapsed >= 14000 && elapsed <= 19000, 'elapsed=' + elapsed);
      console.log('timer elapsed_ms', elapsed);
      await page.getByText('Mock generations: 0', {exact: true}).waitFor();
    });
    await check('reload does not replay the saved release', async () => {
      await page.reload();
      await page.getByText('LessonAI offline notification test', {exact: true}).waitFor();
      assert.equal(await page.locator('iframe').count(), 0);
    });
    async function newVersion(value) {
      await page.getByRole('textbox', {name: 'Release ID'}).fill(value);
      await page.getByRole('textbox', {name: 'Release ID'}).press('Tab');
      await notice.waitFor({state: 'visible'});
    }
    await check('new version can display', () => newVersion('browser_manual_' + Date.now()));
    await check('manual close collapses component and does not regenerate', async () => {
      await frame.locator('#close').click();
      await notice.waitFor({state: 'hidden'});
      await page.waitForSelector('iframe', {state: 'detached'});
      await page.getByRole('textbox', {name: 'Interactive field'}).fill('rerun after manual close');
      await page.getByRole('textbox', {name: 'Interactive field'}).press('Tab');
      await page.getByText('Mock generations: 0', {exact: true}).waitFor();
      assert.equal(await page.locator('iframe').count(), 0);
    });
    await check('navigation away and return do not replay', async () => {
      await newVersion('browser_navigation_' + Date.now());
      await page.getByText('Мои занятия', {exact: true}).click();
      await notice.waitFor({state: 'hidden'});
      await page.getByText('Главная', {exact: true}).click();
      await page.waitForSelector('iframe', {state: 'detached'});
      await page.getByText('LessonAI offline notification test', {exact: true}).waitFor();
      assert.equal(await page.locator('iframe').count(), 0);
    });
    await check('mobile Kazakh version fits viewport and keeps controls usable', async () => {
      const mobileURL = new URL(baseURL);
      mobileURL.searchParams.set('qa_mobile', '1');
      mobileURL.searchParams.set('qa_language', 'kk');
      mobileURL.searchParams.set('qa_release_id', 'browser_mobile_' + Date.now());
      await page.setViewportSize({width: 390, height: 844});
      await page.goto(mobileURL.toString());
      await notice.waitFor({state: 'visible'});
      await frame.locator('#close[aria-label="Жабу"]').waitFor();
      assert.equal(await frame.locator('#title').textContent(), 'LessonAI жаңартылды!');
      const child = page.frames().find(f => f.url().includes('component/'));
      const size = await child.evaluate(() => ({
        width: document.documentElement.clientWidth, content: document.documentElement.scrollWidth,
        right: document.getElementById('notice').getBoundingClientRect().right,
      }));
      assert(size.content <= size.width && size.right <= size.width, JSON.stringify(size));
      await page.getByRole('textbox', {name: 'Interactive field'}).fill('mobile input');
      await page.screenshot({path: 'docs/qa/q/release_notice_mobile.png', fullPage: true});
      await frame.locator('#close').click();
      await notice.waitFor({state: 'hidden'});
    });
    await check('fresh browser context reads persistent account seen state', async () => {
      const second = await browser.newContext();
      const other = await second.newPage();
      await other.goto(baseURL);
      await other.getByText('LessonAI offline notification test', {exact: true}).waitFor();
      assert.equal(await other.locator('iframe').count(), 0);
      await second.close();
    });
    await context.close();
    console.log(`Browser checks passed: ${passed}`);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
