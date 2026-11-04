const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '..', '..');

// The generator deletes this legacy page by name. The filename is not copy.
const ALLOWLIST = ['suno-lyric-video.html'];

const TEXT_EXTENSIONS = new Set(['.py', '.html', '.txt', '.xml', '.md', '.json', '.css', '.js', '.cjs', '.mjs']);

function scrub(text) {
  let out = text;
  for (const token of ALLOWLIST) out = out.split(token).join('');
  return out;
}

function collect(dir, acc) {
  if (!fs.existsSync(dir)) return acc;
  for (const name of fs.readdirSync(dir)) {
    const full = path.join(dir, name);
    const stat = fs.statSync(full);
    if (stat.isDirectory()) collect(full, acc);
    else if (TEXT_EXTENSIONS.has(path.extname(name).toLowerCase())) acc.push(full);
  }
  return acc;
}

function marketingFiles() {
  const listed = [
    'scripts/build_marketing.py',
    'scripts/generate_og_image.py',
    'README.md',
    'frontend/index.html',
    'frontend/pricing.html',
    'frontend/karaoke.html',
    'frontend/contact.html',
    'frontend/terms.html',
    'frontend/privacy.html',
    'frontend/refunds.html',
    'frontend/llms.txt',
    'frontend/sitemap.xml',
    'frontend/robots.txt',
    'frontend/_redirects',
    'frontend/functions/_middleware.js',
    'docs/marketing/campaigns/launch_package_all_channels.md',
    'docs/marketing/campaigns/reddit_leads_2026-10-31.md',
    'docs/marketing/youtube/channel-copy-en.txt',
    'docs/marketing/youtube/tutorial-01-en.md',
    'docs/marketing/youtube/README.md',
  ];
  const found = new Set(listed.map(rel => path.join(root, rel)));
  for (const rel of ['frontend/marketing', 'docs/marketing']) {
    for (const full of collect(path.join(root, rel), [])) found.add(full);
  }
  return [...found].filter(full => fs.existsSync(full)).sort();
}

function offending(text, pattern) {
  const hits = [];
  text.split('\n').forEach((line, index) => {
    if (pattern.test(line)) hits.push(`${index + 1}: ${line.trim().slice(0, 180)}`);
  });
  return hits;
}

test('public marketing output and sources do not use the Suno trademark', () => {
  assert.equal(fs.existsSync(path.join(root, 'frontend/suno-lyric-video.html')), false);
  const problems = [];
  for (const full of marketingFiles()) {
    const rel = path.relative(root, full);
    const hits = offending(scrub(fs.readFileSync(full, 'utf8')), /suno/i);
    for (const hit of hits) problems.push(`${rel}:${hit}`);
  }
  assert.deepEqual(problems, []);
});

test('public marketing copy is not positioned as a tool for third-party music generators', () => {
  const problems = [];
  const patterns = [
    /\budio\b/i,
    /\bai[\s-]*songs?\b/i,
    /\bai[\s-]*music\b/i,
    /ai-generated/i,
    /ai音乐/i,
  ];
  for (const full of marketingFiles()) {
    const rel = path.relative(root, full);
    const text = fs.readFileSync(full, 'utf8');
    for (const pattern of patterns) {
      for (const hit of offending(text, pattern)) problems.push(`${rel}:${hit}`);
    }
  }
  assert.deepEqual(problems, []);
});

// The privacy page states that an external service may receive inputs. That sentence
// is generated from scripts/build_marketing.py, so the same phrase is allowed there
// and nowhere else.
const PRIVACY_DISCLOSURE = 'external AI or media service';

function scrubDisclosure(rel, text) {
  if (rel === 'frontend/privacy.html' || rel === 'scripts/build_marketing.py') {
    return text.split(PRIVACY_DISCLOSURE).join('external media service');
  }
  return text;
}

test('public marketing copy does not use AI wording except the privacy disclosure', () => {
  const problems = [];
  const patterns = [/\bAI\b/, /AI /, /AI对齐/, /人工智能/];
  for (const full of marketingFiles()) {
    const rel = path.relative(root, full);
    const text = scrubDisclosure(rel, fs.readFileSync(full, 'utf8'));
    if (rel === 'frontend/privacy.html' && fs.readFileSync(full, 'utf8').split(PRIVACY_DISCLOSURE).length !== 2) {
      problems.push(`${rel}: expected exactly one privacy disclosure`);
    }
    for (const pattern of patterns) {
      for (const hit of offending(text, pattern)) problems.push(`${rel}:${hit}`);
    }
  }
  assert.deepEqual(problems, []);
});
