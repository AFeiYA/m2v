/**
 * Automated local browser check for Remotion Preview.
 * Verifies that all visual modes (kinetic, tv, apple) render in the browser
 * without TDZ errors (e.g. Cannot access 'O' before initialization) or alert crashes.
 */
import { chromium } from 'playwright-core';

const PORT = 8000;
const URL = `http://127.0.0.1:${PORT}/motion-studio?project=Jingle%20Bells`;

async function runCheck() {
  console.log(`[test-preview-render] Launching browser check against ${URL}...`);
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const page = await browser.newPage({ viewport: { width: 1400, height: 850 } });

  const pageErrors = [];
  page.on('pageerror', err => pageErrors.push(err.message));
  page.on('console', msg => {
    if (msg.type() === 'error') {
      const txt = msg.text();
      // Ignore routine 404s for optional assets
      if (!txt.includes('404')) {
        pageErrors.push(txt);
      }
    }
  });

  try {
    await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 10000 });
    await page.waitForTimeout(2500);

    // 1. Check initial mode (kinetic)
    let alert = await page.evaluate(() => document.querySelector('[role="alert"]')?.textContent);
    if (alert) throw new Error(`Kinetic mode failed: ${alert}`);
    console.log('✓ Kinetic mode preview initialized cleanly');

    // 2. Switch to TV mode (Dual-line KTV)
    const tvCard = await page.$('.template-card[data-template-id="tv"]');
    if (tvCard) {
      await tvCard.click();
      await page.waitForTimeout(1500);
      alert = await page.evaluate(() => document.querySelector('[role="alert"]')?.textContent);
      if (alert) throw new Error(`TV mode failed: ${alert}`);
      console.log('✓ TV mode (Dual-line KTV) preview initialized cleanly');
    }

    // 3. Switch to Apple mode (Apple Music scroll)
    const appleCard = await page.$('.template-card[data-template-id="apple"]');
    if (appleCard) {
      await appleCard.click();
      await page.waitForTimeout(1500);
      alert = await page.evaluate(() => document.querySelector('[role="alert"]')?.textContent);
      if (alert) throw new Error(`Apple mode failed: ${alert}`);
      console.log('✓ Apple mode preview initialized cleanly');
    }

    if (pageErrors.length > 0) {
      throw new Error(`Encountered page errors during preview:\n${pageErrors.join('\n')}`);
    }

    console.log('✅ All visual modes passed local preview check without error!');
  } finally {
    await browser.close();
  }
}

runCheck().catch(err => {
  console.error('❌ Local preview check failed:', err.message);
  process.exit(1);
});
