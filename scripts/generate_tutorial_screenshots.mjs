/**
 * Generates high-resolution 1920x1080 screenshots for the 6 scenes of the tutorial video.
 * Uses real Fovea Studio design tokens, typography, and a sample song with lyrics.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const require = createRequire(path.join(ROOT, 'frontend/motion/package.json'));
const { chromium } = require('playwright-core');
const OUT_DIR = '/Users/luca/Downloads/Fovea_Tutorial_Screenshots';
fs.mkdirSync(OUT_DIR, { recursive: true });

const CHROME_PATH = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

async function main() {
  console.log('🚀 Launching Chromium...');
  const browser = await chromium.launch({
    executablePath: CHROME_PATH,
    headless: true,
    args: ['--font-render-hinting=none', '--force-color-profile=srgb'],
  });

  const context = await browser.newContext({
    viewport: { width: 1920, height: 1080 },
    deviceScaleFactor: 2, // 2x Retina for crisp 4K-ready screenshots
  });

  const page = await context.newPage();

  // -------------------------------------------------------------
  // Scene 1: Finished MV High-Impact Showcase
  // -------------------------------------------------------------
  console.log('📸 Rendering Scene 1: Finished MV Showcase...');
  const scene1Html = `
  <!doctype html>
  <html>
  <head>
    <meta charset="utf-8">
    <link rel="stylesheet" href="file://${ROOT}/frontend/marketing/site.css">
    <style>
      body {
        margin: 0; padding: 0; background: #0b0e09; color: #f5f9ee;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        width: 1920px; height: 1080px; overflow: hidden; display: flex; flex-direction: column;
        box-sizing: border-box; justify-content: space-between; padding: 60px 100px;
        background: radial-gradient(circle at 80% 20%, rgba(183, 243, 74, 0.08), transparent 50%),
                    radial-gradient(circle at 20% 80%, rgba(99, 102, 241, 0.08), transparent 50%), #0d110a;
      }
      header {
        display: flex; justify-content: space-between; align-items: center; width: 100%;
      }
      .brand { display: flex; align-items: center; gap: 14px; text-decoration: none; }
      .brand-badge {
        width: 44px; height: 44px; background: #b7f34a; border-radius: 12px; display: flex;
        align-items: center; justify-content: center; color: #11130e; font-weight: 900; font-size: 24px;
      }
      .brand-title { font-size: 28px; font-weight: 800; letter-spacing: -0.5px; color: #f5f9ee; }
      .brand-sub { color: #8a9680; font-size: 16px; margin-left: 8px; font-weight: 500; }
      .tag-pill {
        background: rgba(183, 243, 74, 0.12); border: 1px solid rgba(183, 243, 74, 0.3);
        color: #b7f34a; padding: 8px 18px; border-radius: 999px; font-size: 15px; font-weight: 700;
        letter-spacing: 0.5px; text-transform: uppercase;
      }
      .showcase-grid {
        display: grid; grid-template-columns: 1.1fr 1fr; gap: 60px; align-items: center; flex: 1; margin: 40px 0;
      }
      .showcase-left {
        display: flex; flex-direction: column; gap: 24px;
      }
      .eyebrow {
        color: #b7f34a; font-size: 18px; font-weight: 800; letter-spacing: 2px; text-transform: uppercase;
      }
      h1 {
        font-size: 64px; font-weight: 900; line-height: 1.1; margin: 0; letter-spacing: -1.5px;
      }
      h1 span { color: #b7f34a; }
      .song-meta-box {
        background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 16px; padding: 20px 24px; display: flex; align-items: center; gap: 20px;
        width: fit-content;
      }
      .song-cover-dummy {
        width: 56px; height: 56px; border-radius: 12px; background: linear-gradient(135deg, #6366f1, #a855f7);
        display: flex; align-items: center; justify-content: center; font-size: 28px;
      }
      .song-name { font-size: 20px; font-weight: 700; color: #fff; margin: 0 0 4px 0; }
      .song-artist { font-size: 14px; color: #8a9680; margin: 0; }
      .previews-wrap {
        display: flex; gap: 28px; align-items: center; justify-content: flex-end;
      }
      .phone-frame {
        width: 320px; height: 560px; border-radius: 36px; border: 4px solid #2a3424;
        background: #11140e; position: relative; overflow: hidden;
        box-shadow: 0 30px 80px rgba(0,0,0,0.8), 0 0 40px rgba(183, 243, 74, 0.15);
        display: flex; flex-direction: column; justify-content: center; padding: 32px;
      }
      .phone-glow {
        position: absolute; top: -50px; left: -50px; width: 400px; height: 400px;
        background: radial-gradient(circle, rgba(183, 243, 74, 0.25), transparent 70%);
        pointer-events: none;
      }
      .phone-lyric-past { color: #495442; font-size: 20px; font-weight: 600; margin: 12px 0; filter: blur(0.5px); }
      .phone-lyric-active { color: #f5f9ee; font-size: 28px; font-weight: 800; margin: 16px 0; line-height: 1.3; text-shadow: 0 0 20px rgba(183, 243, 74, 0.4); }
      .phone-lyric-active span { color: #b7f34a; }
      .phone-lyric-next { color: #495442; font-size: 20px; font-weight: 600; margin: 12px 0; }
      .landscape-frame {
        width: 480px; height: 270px; border-radius: 20px; border: 3px solid #2a3424;
        background: #12160f; box-shadow: 0 20px 60px rgba(0,0,0,0.8);
        position: relative; overflow: hidden; display: flex; flex-direction: column;
        justify-content: flex-end; padding: 24px;
      }
      .karaoke-lead { font-size: 22px; font-weight: 800; color: #fff; margin: 4px 0; }
      .karaoke-lead span { color: #b7f34a; }
      .karaoke-sub { font-size: 16px; color: #627059; margin: 4px 0; }
      footer {
        display: flex; justify-content: space-between; align-items: center; color: #627059; font-size: 15px;
      }
    </style>
  </head>
  <body>
    <header>
      <div class="brand">
        <div class="brand-badge">F</div>
        <span class="brand-title">Fovea <span class="brand-sub">Studio</span></span>
      </div>
      <div class="tag-pill">Step 01 · Preview The Look</div>
    </header>

    <div class="showcase-grid">
      <div class="showcase-left">
        <div class="eyebrow">YOUR MUSIC IN MOTION</div>
        <h1>Turn your song and lyrics into <span>a lyric video</span></h1>
        <div class="song-meta-box">
          <div class="song-cover-dummy">🎵</div>
          <div>
            <p class="song-name">ZeroSOE (Z偏离中线)</p>
            <p class="song-artist">Your track and lyrics · Made with Fovea</p>
          </div>
        </div>
      </div>

      <div class="previews-wrap">
        <div class="phone-frame">
          <div class="phone-glow"></div>
          <div class="phone-lyric-past">镜子里的我，角度刚刚好</div>
          <div class="phone-lyric-active">偏离中线，<span>我自成焦点！</span></div>
          <div class="phone-lyric-next">Zero! S-O-E! Six-one-eight</div>
        </div>
        <div class="landscape-frame">
          <div class="karaoke-lead">偏离中线，<span>我自成焦点！</span></div>
          <div class="karaoke-sub">Zero! S-O-E! Six-one-eight, frequency</div>
        </div>
      </div>
    </div>

    <footer>
      <span>mv.fovea.si</span>
      <span>16:9 Landscape &amp; 9:16 Portrait Support</span>
    </footer>
  </body>
  </html>
  `;
  await page.setContent(scene1Html);
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${OUT_DIR}/Scene_01_Intro_Finished_MV.png` });
  console.log('✅ Scene 1 Saved!');

  // -------------------------------------------------------------
  // Scene 2: Import a public song link (Live App)
  // -------------------------------------------------------------
  console.log('📸 Rendering Scene 2: Import a song link...');
  await page.goto('https://mv.fovea.si/app', { waitUntil: 'networkidle' });
  await page.evaluate(() => {
    const overlay = document.getElementById('auth-overlay');
    if (overlay) overlay.style.display = 'none';
    const app = document.getElementById('app');
    if (app) app.style.display = '';
    const creds = document.getElementById('sidebar-credits-num');
    if (creds) creds.textContent = '880';
    const userCreds = document.getElementById('user-credits');
    if (userCreds) userCreds.textContent = '880 available';
    const userLabel = document.getElementById('user-info');
    if (userLabel) userLabel.textContent = 'Luca';
    window.location.hash = '#upload-section';
    const sec = document.getElementById('section-upload');
    if (sec) sec.style.display = '';
  });
  await page.waitForTimeout(600);
  const inputSuno = page.locator('#input-suno-url');
  await inputSuno.fill('https://example.com/song/demo');
  await inputSuno.focus();
  await page.screenshot({ path: `${OUT_DIR}/Scene_02_Import_Song_Link.png` });
  console.log('✅ Scene 2 Saved!');

  // -------------------------------------------------------------
  // Scene 3: Lyric Studio (Precision Word Alignment & Waveform)
  // -------------------------------------------------------------
  console.log('📸 Rendering Scene 3: Lyric Studio Precision Timing...');
  const scene3Html = `
  <!doctype html>
  <html>
  <head>
    <meta charset="utf-8">
    <style>
      body {
        margin: 0; padding: 0; background: #0c0f0a; color: #e2e8f0;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        width: 1920px; height: 1080px; overflow: hidden; display: flex; flex-direction: column;
      }
      header {
        height: 64px; background: #12160e; border-bottom: 1px solid #232c1c; display: flex;
        align-items: center; justify-content: space-between; padding: 0 32px;
      }
      .brand-box { display: flex; align-items: center; gap: 12px; }
      .pill-badge { background: #b7f34a; color: #111; font-weight: 800; border-radius: 6px; padding: 4px 10px; font-size: 13px; }
      .track-title { font-size: 16px; font-weight: 700; color: #fff; }
      .track-status { color: #8a9680; font-size: 13px; margin-left: 8px; }
      .header-actions { display: flex; gap: 12px; align-items: center; }
      .btn { padding: 8px 18px; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; border: 1px solid transparent; }
      .btn-outline { background: rgba(255,255,255,0.06); border-color: #334155; color: #e2e8f0; }
      .btn-primary { background: #b7f34a; color: #111; font-weight: 700; }
      .workspace {
        display: grid; grid-template-columns: 460px 1fr; flex: 1; overflow: hidden;
      }
      .lyrics-panel {
        background: #11150d; border-right: 1px solid #232c1c; padding: 24px; display: flex;
        flex-direction: column; gap: 16px; overflow-y: auto;
      }
      .panel-head { font-size: 12px; font-weight: 800; color: #627059; text-transform: uppercase; letter-spacing: 1px; }
      .lyric-row {
        padding: 16px 20px; border-radius: 12px; background: rgba(255,255,255,0.02);
        border: 1px solid rgba(255,255,255,0.04); display: flex; flex-direction: column; gap: 6px;
      }
      .lyric-row.active {
        background: rgba(183, 243, 74, 0.08); border-color: rgba(183, 243, 74, 0.4);
      }
      .row-meta { display: flex; justify-content: space-between; font-size: 12px; color: #8a9680; }
      .row-meta .time { font-family: monospace; color: #b7f34a; }
      .row-text { font-size: 17px; font-weight: 600; color: #f1f5f9; }
      .editor-main {
        display: flex; flex-direction: column; background: #0c0f0a; position: relative;
      }
      .timing-visualizer {
        flex: 1; display: flex; flex-direction: column; justify-content: center; padding: 40px 60px; gap: 32px;
      }
      .active-quote {
        font-size: 40px; font-weight: 800; text-align: center; color: #f8fafc; line-height: 1.4;
      }
      .active-quote span.hit {
        color: #b7f34a; background: rgba(183, 243, 74, 0.15); padding: 2px 10px; border-radius: 8px;
        box-shadow: 0 0 20px rgba(183, 243, 74, 0.3);
      }
      .waveform-container {
        background: #12170e; border: 1px solid #28331f; border-radius: 20px; padding: 32px;
        position: relative; box-shadow: inset 0 0 40px rgba(0,0,0,0.5);
      }
      .waveform-bars {
        height: 120px; display: flex; align-items: center; justify-content: space-between; gap: 3px;
        opacity: 0.85;
      }
      .bar { width: 5px; background: #3c4c2f; border-radius: 3px; }
      .bar.played { background: #b7f34a; box-shadow: 0 0 8px rgba(183, 243, 74, 0.5); }
      .words-timeline {
        display: flex; gap: 12px; margin-top: 24px; position: relative;
      }
      .word-pill {
        flex: 1; background: #1c2417; border: 2px solid #3c4c2f; border-radius: 10px;
        padding: 14px 10px; text-align: center; font-size: 18px; font-weight: 700;
        position: relative; color: #f1f5f9;
      }
      .word-pill.active {
        background: rgba(183, 243, 74, 0.18); border-color: #b7f34a; color: #b7f34a;
        box-shadow: 0 0 25px rgba(183, 243, 74, 0.25);
      }
      .word-pill .handle {
        position: absolute; right: -6px; top: 20%; height: 60%; width: 10px;
        background: #b7f34a; border-radius: 4px; cursor: ew-resize; box-shadow: 0 0 10px #b7f34a;
      }
      .word-pill .time-tag {
        font-size: 11px; font-family: monospace; color: #8a9680; margin-top: 4px;
      }
      .playhead-line {
        position: absolute; top: 0; bottom: 0; left: 48%; width: 3px; background: #b7f34a;
        box-shadow: 0 0 16px #b7f34a; z-index: 10;
      }
      .transport-bar {
        height: 80px; background: #12160e; border-top: 1px solid #232c1c; display: flex;
        align-items: center; justify-content: space-between; padding: 0 40px;
      }
      .transport-controls { display: flex; align-items: center; gap: 20px; }
      .play-btn {
        width: 48px; height: 48px; border-radius: 50%; background: #b7f34a; color: #111;
        display: flex; align-items: center; justify-content: center; font-size: 20px; font-weight: 900;
      }
    </style>
  </head>
  <body>
    <header>
      <div class="brand-box">
        <span class="pill-badge">Lyric Studio</span>
        <span class="track-title">ZeroSOE (Z偏离中线)</span>
        <span class="track-status">· Word-level Acoustic Alignment</span>
      </div>
      <div class="header-actions">
        <button class="btn btn-outline">Split Line</button>
        <button class="btn btn-outline">Merge Line</button>
        <button class="btn btn-primary">Save Timing ✓</button>
      </div>
    </header>

    <div class="workspace">
      <div class="lyrics-panel">
        <div class="panel-head">Aligned Lyrics</div>
        <div class="lyric-row">
          <div class="row-meta"><span>Line 1</span><span class="time">00:01.200 - 00:03.450</span></div>
          <div class="row-text">Zero. SOE · Perfect? Almost.</div>
        </div>
        <div class="lyric-row">
          <div class="row-meta"><span>Line 2</span><span class="time">00:03.600 - 00:06.800</span></div>
          <div class="row-text">镜子里的我，角度刚刚好</div>
        </div>
        <div class="lyric-row active">
          <div class="row-meta"><span>Chorus (Active)</span><span class="time">00:15.120 - 00:19.450</span></div>
          <div class="row-text">偏离中线，我自成焦点！</div>
        </div>
        <div class="lyric-row">
          <div class="row-meta"><span>Line 4</span><span class="time">00:19.600 - 00:23.200</span></div>
          <div class="row-text">Zero! S-O-E! Six-one-eight, frequency</div>
        </div>
      </div>

      <div class="editor-main">
        <div class="timing-visualizer">
          <div class="active-quote">
            偏离中线，<span class="hit">我自成焦点！</span>
          </div>

          <div class="waveform-container">
            <div class="playhead-line"></div>
            <div class="waveform-bars">
              ${Array.from({ length: 90 }).map((_, i) => {
                const height = Math.sin(i * 0.25) * 40 + Math.cos(i * 0.1) * 30 + 50;
                const played = i < 44;
                return `<div class="bar ${played ? 'played' : ''}" style="height: ${Math.max(12, height)}px;"></div>`;
              }).join('')}
            </div>

            <div class="words-timeline">
              <div class="word-pill">偏离<div class="time-tag">15.12s</div></div>
              <div class="word-pill">中线<div class="time-tag">15.80s</div></div>
              <div class="word-pill active">
                我自成
                <div class="handle" title="Drag to snap timing boundary"></div>
                <div class="time-tag">16.45s</div>
              </div>
              <div class="word-pill active">焦点！<div class="time-tag">17.20s</div></div>
            </div>
          </div>
        </div>

        <div class="transport-bar">
          <div class="transport-controls">
            <div class="play-btn">▶</div>
            <span style="font-family: monospace; font-size: 16px; color: #b7f34a;">00:16.850 / 02:45.000</span>
          </div>
          <div style="font-size: 14px; color: #8a9680;">
            ⚡ Drag boundary handles to snap timing · Shift+Click to solo audition
          </div>
        </div>
      </div>
    </div>
  </body>
  </html>
  `;
  await page.setContent(scene3Html);
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT_DIR}/Scene_03_Lyric_Studio_Alignment.png` });
  console.log('✅ Scene 3 Saved!');

  // -------------------------------------------------------------
  // Scene 4: Motion Studio (3 Visual Styles & Format Toggle)
  // -------------------------------------------------------------
  console.log('📸 Rendering Scene 4: Motion Studio 3 Styles...');
  const scene4Html = `
  <!doctype html>
  <html>
  <head>
    <meta charset="utf-8">
    <style>
      body {
        margin: 0; padding: 0; background: #0c0f0a; color: #e2e8f0;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        width: 1920px; height: 1080px; overflow: hidden; display: flex; flex-direction: column;
      }
      header {
        height: 64px; background: #12160e; border-bottom: 1px solid #232c1c; display: flex;
        align-items: center; justify-content: space-between; padding: 0 32px;
      }
      .brand-box { display: flex; align-items: center; gap: 12px; }
      .pill-badge { background: #6366f1; color: #fff; font-weight: 800; border-radius: 6px; padding: 4px 10px; font-size: 13px; }
      .track-title { font-size: 16px; font-weight: 700; color: #fff; }
      .format-switch {
        background: #1a2214; border: 1px solid #334155; border-radius: 999px; padding: 4px; display: flex; gap: 4px;
      }
      .format-btn {
        padding: 6px 14px; border-radius: 999px; font-size: 12px; font-weight: 700; border: none; cursor: pointer; color: #8a9680; background: transparent;
      }
      .format-btn.active { background: #b7f34a; color: #111; }
      .workspace {
        display: grid; grid-template-columns: 380px 1fr 340px; flex: 1; overflow: hidden;
      }
      .styles-panel {
        background: #11150d; border-right: 1px solid #232c1c; padding: 24px; display: flex; flex-direction: column; gap: 20px;
      }
      .panel-head { font-size: 12px; font-weight: 800; color: #627059; text-transform: uppercase; letter-spacing: 1px; }
      .style-card {
        padding: 18px; border-radius: 14px; background: rgba(255,255,255,0.02); border: 2px solid rgba(255,255,255,0.05);
        cursor: pointer; display: flex; flex-direction: column; gap: 6px;
      }
      .style-card.selected {
        border-color: #b7f34a; background: rgba(183, 243, 74, 0.08); box-shadow: 0 0 20px rgba(183, 243, 74, 0.15);
      }
      .style-name { font-size: 16px; font-weight: 800; color: #fff; }
      .style-desc { font-size: 13px; color: #8a9680; line-height: 1.4; }
      .stage-center {
        display: flex; flex-direction: column; align-items: center; justify-content: center; background: #080a06;
        position: relative;
      }
      .stage-canvas {
        width: 450px; height: 800px; border-radius: 28px; background: #11140e; border: 3px solid #232c1c;
        box-shadow: 0 30px 90px rgba(0,0,0,0.8), 0 0 50px rgba(183, 243, 74, 0.15);
        position: relative; overflow: hidden; display: flex; flex-direction: column; justify-content: center; padding: 40px;
      }
      .glow-orb {
        position: absolute; top: -60px; right: -60px; width: 400px; height: 400px;
        background: radial-gradient(circle, rgba(183, 243, 74, 0.3), transparent 70%);
      }
      .lyric-item { font-size: 26px; font-weight: 600; color: #3c4c2f; margin: 18px 0; }
      .lyric-item.current {
        font-size: 38px; font-weight: 900; color: #f5f9ee; line-height: 1.25;
        text-shadow: 0 0 25px rgba(183, 243, 74, 0.4);
      }
      .lyric-item.current span { color: #b7f34a; }
      .inspector-panel {
        background: #11150d; border-left: 1px solid #232c1c; padding: 24px; display: flex; flex-direction: column; gap: 24px;
      }
      .color-palette-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-top: 10px; }
      .color-dot { height: 36px; border-radius: 8px; border: 2px solid transparent; cursor: pointer; }
      .color-dot.active { border-color: #fff; }
    </style>
  </head>
  <body>
    <header>
      <div class="brand-box">
        <span class="pill-badge">Motion Studio</span>
        <span class="track-title">ZeroSOE (Z偏离中线) · Visual Director</span>
      </div>
      <div class="format-switch">
        <button class="format-btn active">9:16 Portrait (TikTok/Reels)</button>
        <button class="format-btn">16:9 Landscape (YouTube MV)</button>
      </div>
      <button style="background: #b7f34a; border: none; border-radius: 8px; font-weight: 800; padding: 8px 18px; color: #111;">
        Ready to Export ➔
      </button>
    </header>

    <div class="workspace">
      <div class="styles-panel">
        <div class="panel-head">Select Motion Style</div>
        <div class="style-card selected">
          <div class="style-name">01 · Apple Music Ambient</div>
          <div class="style-desc">Dynamic glowing fluid typography, soft backdrop diffusion, and active word pulse.</div>
        </div>
        <div class="style-card">
          <div class="style-name">02 · Dual-line Karaoke</div>
          <div class="style-desc">Crisp horizontal sweep. Clear 2-line preview of incoming vocal phrasing.</div>
        </div>
        <div class="style-card">
          <div class="style-name">03 · Kinetic Poster</div>
          <div class="style-desc">High-energy beat drops, bold graphic hierarchy, perfect for EDM and bass hits.</div>
        </div>
      </div>

      <div class="stage-center">
        <div class="stage-canvas">
          <div class="glow-orb"></div>
          <div class="lyric-item">镜子里的我，角度刚刚好</div>
          <div class="lyric-item current">偏离中线，<br><span>我自成焦点！</span></div>
          <div class="lyric-item">Zero! S-O-E! Six-one-eight</div>
        </div>
      </div>

      <div class="inspector-panel">
        <div class="panel-head">Theme &amp; Aesthetics</div>
        <div>
          <label style="font-size: 13px; color: #8a9680;">Palette</label>
          <div class="color-palette-grid">
            <div class="color-dot active" style="background: linear-gradient(135deg, #b7f34a, #111);"></div>
            <div class="color-dot" style="background: linear-gradient(135deg, #6366f1, #111);"></div>
            <div class="color-dot" style="background: linear-gradient(135deg, #ec4899, #111);"></div>
            <div class="color-dot" style="background: linear-gradient(135deg, #e2e8f0, #111);"></div>
          </div>
        </div>
        <div>
          <label style="font-size: 13px; color: #8a9680;">Artwork Crop</label>
          <div style="background: #182013; padding: 12px; border-radius: 8px; margin-top: 8px; font-size: 13px;">
            ✓ Cached cover active
          </div>
        </div>
      </div>
    </div>
  </body>
  </html>
  `;
  await page.setContent(scene4Html);
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT_DIR}/Scene_04_Motion_Studio_Styles.png` });
  console.log('✅ Scene 4 Saved!');

  // -------------------------------------------------------------
  // Scene 5: Export Matrix Dialog (10 Credits Buyout & Batch)
  // -------------------------------------------------------------
  console.log('📸 Rendering Scene 5: Export Matrix Dialog...');
  const scene5Html = `
  <!doctype html>
  <html>
  <head>
    <meta charset="utf-8">
    <style>
      body {
        margin: 0; padding: 0; background: rgba(11, 14, 9, 0.94); color: #e2e8f0;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        width: 1920px; height: 1080px; overflow: hidden; display: flex; align-items: center; justify-content: center;
        background: radial-gradient(circle, rgba(183, 243, 74, 0.08), transparent 60%), #0c0f0a;
      }
      .modal-card {
        width: 820px; background: #13180f; border: 1px solid #2d3a22; border-radius: 24px;
        box-shadow: 0 40px 100px rgba(0,0,0,0.9), 0 0 60px rgba(183, 243, 74, 0.15);
        padding: 40px 48px; display: flex; flex-direction: column; gap: 28px;
      }
      .modal-header {
        display: flex; justify-content: space-between; align-items: flex-start;
      }
      .title-group h2 { font-size: 28px; font-weight: 800; color: #fff; margin: 0 0 6px 0; }
      .title-group p { font-size: 15px; color: #8a9680; margin: 0; }
      .buyout-badge {
        background: rgba(183, 243, 74, 0.15); border: 1px solid #b7f34a; color: #b7f34a;
        padding: 8px 16px; border-radius: 999px; font-size: 13px; font-weight: 800;
      }
      .batch-list { display: flex; flex-direction: column; gap: 14px; }
      .batch-item {
        background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.07);
        border-radius: 14px; padding: 18px 24px; display: flex; align-items: center; justify-content: space-between;
      }
      .batch-item.checked {
        border-color: rgba(183, 243, 74, 0.4); background: rgba(183, 243, 74, 0.04);
      }
      .item-left { display: flex; align-items: center; gap: 16px; }
      .check-box {
        width: 22px; height: 22px; border-radius: 6px; background: #b7f34a; color: #111;
        display: flex; align-items: center; justify-content: center; font-weight: 900; font-size: 14px;
      }
      .item-name { font-size: 16px; font-weight: 700; color: #fff; }
      .item-desc { font-size: 13px; color: #8a9680; }
      .item-cost { font-size: 14px; font-weight: 800; color: #b7f34a; }
      .cost-summary-box {
        background: #192213; border: 1px solid #2d3c21; border-radius: 14px; padding: 20px 24px;
        display: flex; justify-content: space-between; align-items: center;
      }
      .cost-info h4 { margin: 0 0 4px 0; font-size: 15px; color: #fff; }
      .cost-info p { margin: 0; font-size: 13px; color: #8a9680; }
      .cost-digits { font-size: 26px; font-weight: 900; color: #b7f34a; }
      .btn-export-confirm {
        background: #b7f34a; color: #111; padding: 18px; border-radius: 14px; border: none;
        font-size: 17px; font-weight: 800; cursor: pointer; text-align: center;
        box-shadow: 0 10px 30px rgba(183, 243, 74, 0.3);
      }
    </style>
  </head>
  <body>
    <div class="modal-card">
      <div class="modal-header">
        <div class="title-group">
          <h2>Export Video Matrix</h2>
          <p>ZeroSOE · 10-credit single-song buyout unlocks unlimited browser exports</p>
        </div>
        <div class="buyout-badge">⚡ 10 CREDITS BUYOUT</div>
      </div>

      <div class="batch-list">
        <div class="batch-item checked">
          <div class="item-left">
            <div class="check-box">✓</div>
            <div>
              <div class="item-name">Full Song (16:9 Landscape)</div>
              <div class="item-desc">YouTube Full MV · 1920×1080 · 60fps</div>
            </div>
          </div>
          <div class="item-cost">Included</div>
        </div>

        <div class="batch-item checked">
          <div class="item-left">
            <div class="check-box">✓</div>
            <div>
              <div class="item-name">Full Song (9:16 Portrait)</div>
              <div class="item-desc">TikTok / Reels / Shorts · 1080×1920</div>
            </div>
          </div>
          <div class="item-cost">Included</div>
        </div>

        <div class="batch-item checked">
          <div class="item-left">
            <div class="check-box">✓</div>
            <div>
              <div class="item-name">Chorus Highlight Clip ("偏离中线，我自成焦点！")</div>
              <div class="item-desc">High-energy 15s teaser · 9:16 Vertical</div>
            </div>
          </div>
          <div class="item-cost">Included</div>
        </div>
      </div>

      <div class="cost-summary-box">
        <div class="cost-info">
          <h4>Single-Song Video Buyout</h4>
          <p>Subsequent exports across all layouts &amp; clips will be 0 credits (Free)</p>
        </div>
        <div class="cost-digits">10 credits</div>
      </div>

      <button class="btn-export-confirm">
        Start Fast Browser Export (3 Videos) ➔
      </button>
    </div>
  </body>
  </html>
  `;
  await page.setContent(scene5Html);
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT_DIR}/Scene_05_Export_Matrix_Buyout.png` });
  console.log('✅ Scene 5 Saved!');

  // -------------------------------------------------------------
  // Scene 6: Outro / Ready to Share (My Exports)
  // -------------------------------------------------------------
  console.log('📸 Rendering Scene 6: Outro Ready to Share...');
  const scene6Html = `
  <!doctype html>
  <html>
  <head>
    <meta charset="utf-8">
    <style>
      body {
        margin: 0; padding: 0; background: #0c0f0a; color: #f5f9ee;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        width: 1920px; height: 1080px; overflow: hidden; display: flex; flex-direction: column;
        justify-content: space-between; padding: 70px 120px; box-sizing: border-box;
        background: radial-gradient(circle at 50% 50%, rgba(183, 243, 74, 0.1), transparent 70%), #0d110a;
      }
      header { display: flex; justify-content: space-between; align-items: center; }
      .brand { display: flex; align-items: center; gap: 14px; }
      .brand-badge {
        width: 48px; height: 48px; background: #b7f34a; border-radius: 12px; display: flex;
        align-items: center; justify-content: center; color: #111; font-weight: 900; font-size: 26px;
      }
      .brand-title { font-size: 32px; font-weight: 800; color: #fff; }
      .center-content {
        display: flex; flex-direction: column; align-items: center; text-align: center; gap: 32px;
      }
      .success-pill {
        background: rgba(183, 243, 74, 0.15); border: 1px solid #b7f34a; color: #b7f34a;
        padding: 8px 20px; border-radius: 999px; font-size: 15px; font-weight: 800;
        letter-spacing: 1px; text-transform: uppercase;
      }
      h1 { font-size: 72px; font-weight: 900; margin: 0; line-height: 1.1; letter-spacing: -2px; }
      h1 span { color: #b7f34a; }
      .export-card-preview {
        background: #141a10; border: 1px solid #2e3d23; border-radius: 20px; padding: 24px 36px;
        display: flex; align-items: center; gap: 28px; width: 680px; text-align: left;
        box-shadow: 0 30px 80px rgba(0,0,0,0.8), 0 0 40px rgba(183, 243, 74, 0.1);
      }
      .video-icon-box {
        width: 64px; height: 64px; border-radius: 16px; background: #b7f34a; color: #111;
        display: flex; align-items: center; justify-content: center; font-size: 28px; font-weight: 900;
      }
      .card-info { flex: 1; }
      .card-title { font-size: 22px; font-weight: 800; color: #fff; margin: 0 0 4px 0; }
      .card-sub { font-size: 14px; color: #8a9680; margin: 0; }
      .btn-download {
        background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.2);
        color: #fff; padding: 12px 24px; border-radius: 10px; font-size: 14px; font-weight: 700;
      }
      .cta-url {
        font-size: 32px; font-weight: 800; color: #b7f34a; text-decoration: none;
        letter-spacing: -0.5px;
      }
      footer { display: flex; justify-content: center; color: #627059; font-size: 16px; }
    </style>
  </head>
  <body>
    <header>
      <div class="brand">
        <div class="brand-badge">F</div>
        <span class="brand-title">Fovea Studio</span>
      </div>
      <div class="success-pill">✓ Export Ready</div>
    </header>

    <div class="center-content">
      <div class="eyebrow" style="color: #b7f34a; font-weight: 800; letter-spacing: 2px;">YOUR MUSIC DESERVES TO BE SEEN</div>
      <h1>Ready to Drop on <span>YouTube &amp; TikTok</span></h1>

      <div class="export-card-preview">
        <div class="video-icon-box">▶</div>
        <div class="card-info">
          <p class="card-title">ZeroSOE_LyricVideo_1080p.mp4</p>
          <p class="card-sub">1080p · 60fps · Ready in My Exports</p>
        </div>
        <div class="btn-download">Download MP4 ⤓</div>
      </div>

      <div class="cta-url">mv.fovea.si</div>
    </div>

    <footer>
      <span>Subscribe for more lyric video masterclasses with Fovea</span>
    </footer>
  </body>
  </html>
  `;
  await page.setContent(scene6Html);
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${OUT_DIR}/Scene_06_Outro_Ready_To_Share.png` });
  console.log('✅ Scene 6 Saved!');

  await browser.close();
  console.log('🎉 All 6 Tutorial Scenes successfully generated in:', OUT_DIR);
}

main().catch(console.error);
