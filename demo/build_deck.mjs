// Screenshot the running app, then render deck.html to out/PathCheck-deck.pdf.
// Needs the app on http://127.0.0.1:8931 (python3 -m pathcheck.server). Run: node build_deck.mjs
import { chromium } from 'playwright-core';
import { mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.join(here, 'out');
mkdirSync(out, { recursive: true });
const app = process.env.APP_URL || 'http://127.0.0.1:8931/';

const browser = await chromium.launch({ channel: 'chrome' });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'light', deviceScaleFactor: 1.5 });
await ctx.addInitScript({ path: path.join(here, 'live_view.js') });
const page = await ctx.newPage();
await page.goto(app);
await page.click('#go');
await page.waitForSelector('.course', { timeout: 180000 });
await page.waitForTimeout(1500);
await page.locator('main#answer').screenshot({ path: path.join(out, 'shot-answer.png') });
await page.locator('aside').screenshot({ path: path.join(out, 'shot-trace.png') });
await page.locator('.cite').last().click();
await page.locator('dialog').screenshot({ path: path.join(out, 'shot-cite.png') });

const deck = await browser.newPage();
await deck.goto('file://' + path.join(here, 'deck.html'));
await deck.waitForLoadState('networkidle');
await deck.pdf({ path: path.join(out, 'PathCheck-deck.pdf'), width: '1920px', height: '1080px', printBackground: true });
await browser.close();
console.log('wrote', path.join(out, 'PathCheck-deck.pdf'));
