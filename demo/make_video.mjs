// Build the demo video: narrated deck slides plus a screen recording of the real app.
// Needs the app on http://127.0.0.1:8931, macOS `say`, and ffmpeg. Run: node make_video.mjs
import { chromium } from 'playwright-core';
import { execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync, readdirSync, renameSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.join(here, 'out', 'video');
mkdirSync(out, { recursive: true });
const app = process.env.APP_URL || 'http://127.0.0.1:8931/';
const FF = process.env.FFMPEG || 'ffmpeg';
const VOICE = process.env.VOICE || 'Samantha';
const QUESTION = "I'm an F-1 student. I finished CS 311 and MATH 322. Can I take CS 400 and CS 560 in Spring 2027, and can one of them be online?";

// kind: slide (deck section index) or app phase. Narration drives each scene's length.
const SCENES = [
  { slide: 0, say: "This is PathCheck. A student asks: can I take this class? And gets a straight answer from the university's own catalog, schedule and policies, with the proof attached." },
  { slide: 1, say: "Today those rules live in four places that don't talk to each other. Advisors carry hundreds of students each. And for an international student, one wrong online class can put their visa status at risk." },
  { app: 'ask', say: "Here, a student on an F-1 visa asks about two computer science classes, and about taking one online. On the right, the agent team works in the open. The planner reads the question. The researcher runs SQL across four sources. The prerequisite engine applies the catalog's rules exactly. And the checker throws out an outdated policy page from 2022 instead of quoting it." },
  { app: 'answer', say: "CS 400: you can take it, and here is the section. CS 560: not yet, and it shows exactly which courses are missing. Every reason carries a source. Click one, and you see the excerpt, the link, and the exact query that found it." },
  { slide: 3, say: "This is not a straight pipeline. Blocked classes branch into path finding. Thin evidence sends the planner back to re-plan. Rejected claims go back to the analyst, up to three rounds, and anything still wrong is removed before the student sees it." },
  { slide: 5, say: "Zetaris is the data layer. The four sources are registered as Lightning REST tables, and every lookup is SQL sent to Zetaris. Meterless provides the World Model engine, the shared, replayable memory every agent writes to with provenance. And Nightshift is the model provider, serving NVIDIA Nemotron on fast, deep and judge lanes." },
  { slide: 4, say: "The stack is small and dependable. Python standard library only, Server-Sent Events streaming every agent step, and unit tests on the engine. A sample mode with a local copy of the data lets anyone run it from a clean clone, and two settings point it at Zetaris and Nightshift." },
  { slide: 6, say: "What makes PathCheck different: the model is never allowed to overrule the catalog. Rules decide eligibility. The model explains it. And every sentence traces back to its source." },
  { slide: 8, say: "Next: full degree audits from a transcript, an advisor inbox, answers in any language, at any university. PathCheck. Answers students can check." },
];

const run = (cmd, args) => execFileSync(cmd, args, { stdio: ['ignore', 'pipe', 'pipe'] }).toString();
const dur = (f) => parseFloat(run('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f]));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 1. Narration
SCENES.forEach((s, i) => {
  s.wav = path.join(out, `n${i}.wav`);
  run('say', ['-v', VOICE, '-r', '175', '-o', s.wav, '--data-format=LEI16@44100', s.say]);
  s.secs = dur(s.wav) + 0.8;
});

const browser = await chromium.launch({ channel: 'chrome' });

// 2. Slides as 1920x1080 stills
const deck = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await deck.goto('file://' + path.join(here, 'deck.html'));
await deck.waitForLoadState('networkidle');
for (const [i, s] of SCENES.entries()) {
  if (s.slide === undefined) continue;
  s.png = path.join(out, `s${i}.png`);
  await deck.locator('section').nth(s.slide).screenshot({ path: s.png });
}

// 3. Screen recording of the app, paced to the two app narrations
const ask = SCENES.find((s) => s.app === 'ask');
const answer = SCENES.find((s) => s.app === 'answer');
const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 }, colorScheme: 'light',
  recordVideo: { dir: out, size: { width: 1600, height: 900 } } });
await ctx.addInitScript({ path: path.join(here, 'live_view.js') });
const page = await ctx.newPage();
const t0 = Date.now();
await page.goto(app);
await page.waitForLoadState('networkidle');
const lead = (Date.now() - t0) / 1000; // trimmed from the start of the recording
const caption = (text) => page.evaluate((t) => {
  let c = document.getElementById('demo-cap');
  if (!c) {
    c = document.createElement('div');
    c.id = 'demo-cap';
    c.style.cssText = 'position:fixed;left:50%;top:14px;transform:translateX(-50%);background:#1b1a17;color:#f6f1e7;font:600 20px "IBM Plex Sans",sans-serif;padding:10px 22px;border-radius:999px;z-index:9999;box-shadow:0 6px 24px #0004';
    document.body.appendChild(c);
  }
  c.textContent = t;
  c.style.display = t ? 'block' : 'none';
}, text);

let phase = Date.now();
await caption('Ask in plain words');
await page.click('#q');
await page.fill('#q', '');
await page.type('#q', QUESTION, { delay: 22 });
await page.click('#go');
await caption('Live agent trace: every step, query and verdict');
// keep the newest trace line in view while the run streams, then hold
const follow = () => page.evaluate(() => {
  const last = document.querySelector('#trace > :last-child');
  if (last) last.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
});
while ((Date.now() - phase) / 1000 < ask.secs - 0.5 || !(await page.$('.course'))) { await follow(); await sleep(400); }

phase = Date.now();
await caption('A verdict per class, with the reasons');
await page.evaluate(() => document.querySelector('main#answer').scrollIntoView({ behavior: 'smooth', block: 'start' }));
await sleep(answer.secs * 450);
await caption('Every reason opens its proof');
await page.locator('.cite').first().click();
while ((Date.now() - phase) / 1000 < answer.secs) await sleep(100);
await caption('');
const vid = await page.video().path();
await ctx.close();
await browser.close();
const appRaw = path.join(out, 'app.webm');
renameSync(vid, appRaw);

// 4. Encode each segment, then join
const enc = ['-r', '30', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'medium', '-crf', '20', '-c:a', 'aac', '-b:a', '160k', '-ar', '44100', '-ac', '2'];
const parts = [];
for (const [i, s] of SCENES.entries()) {
  if (s.app === 'answer') continue; // encoded together with 'ask'
  const seg = path.join(out, `seg${i}.mp4`);
  if (s.png) {
    run(FF, ['-y', '-loglevel', 'error', '-loop', '1', '-t', String(s.secs), '-i', s.png, '-i', s.wav,
      '-filter_complex', '[0:v]scale=1920:1080,fade=t=in:d=0.3[v];[1:a]apad[a]', '-map', '[v]', '-map', '[a]',
      '-t', String(s.secs), ...enc, seg]);
  } else {
    const total = ask.secs + answer.secs;
    run(FF, ['-y', '-loglevel', 'error', '-ss', String(lead), '-i', appRaw, '-i', ask.wav, '-i', answer.wav,
      '-filter_complex',
      `[0:v]crop=1440:810:80:0,scale=1920:1080:flags=lanczos,tpad=stop_mode=clone:stop_duration=5[v];` +
      `[1:a]apad=whole_dur=${ask.secs}[a1];[2:a]apad=whole_dur=${answer.secs}[a2];[a1][a2]concat=n=2:v=0:a=1[a]`,
      '-map', '[v]', '-map', '[a]', '-t', String(total), ...enc, seg]);
  }
  parts.push(seg);
}
const list = path.join(out, 'parts.txt');
writeFileSync(list, parts.map((p) => `file '${p}'`).join('\n'));
const final = path.join(here, 'out', 'PathCheck-demo.mp4');
run(FF, ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', list, '-c', 'copy', '-movflags', '+faststart', final]);
console.log('wrote', final, dur(final).toFixed(1) + 's');
