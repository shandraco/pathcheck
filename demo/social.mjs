// Render social.html to out/linkedin-cover.png (1200x627) and out/linkedin-diagram.png (1080x1350).
import { chromium } from 'playwright-core';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const browser = await chromium.launch({ channel: 'chrome' });
const page = await browser.newPage({ viewport: { width: 1300, height: 1500 }, deviceScaleFactor: 2 });
await page.goto('file://' + path.join(here, 'social.html'));
await page.waitForLoadState('networkidle');
await page.evaluate(() => document.fonts.ready);
await page.locator('#cover').screenshot({ path: path.join(here, 'out', 'linkedin-cover.png') });
await page.locator('#info').screenshot({ path: path.join(here, 'out', 'linkedin-diagram.png') });
await browser.close();
console.log('wrote out/linkedin-cover.png and out/linkedin-diagram.png');
