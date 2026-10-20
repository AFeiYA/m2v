const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

test('motion studio html files include WebCodecs fast export checkbox', () => {
  const html1 = fs.readFileSync(path.join(__dirname, '../local/motion_studio.html'), 'utf8');
  const html2 = fs.readFileSync(path.join(__dirname, '../local/motion_studio_director.html'), 'utf8');

  assert.ok(html1.includes('id="export-fast-webcodecs"'));
  assert.ok(html1.includes('data-i18n="ms_fast_webcodecs"'));
  assert.ok(html2.includes('id="export-fast-webcodecs"'));
  assert.ok(html2.includes('data-i18n="ms_fast_webcodecs"'));
});

test('i18n contains translations for WebCodecs fast export', () => {
  const i18nContent = fs.readFileSync(path.join(__dirname, '../local/i18n.js'), 'utf8');
  assert.ok(i18nContent.includes('ms_fast_webcodecs'));
  assert.ok(i18nContent.includes('ms_help_export_webcodecs'));
});

test('webcodecs-exporter module exports isWebCodecsSupported and exportMotionWebCodecs', () => {
  const exporterContent = fs.readFileSync(path.join(__dirname, '../motion/src/webcodecs-exporter.ts'), 'utf8');
  assert.ok(exporterContent.includes('export function isWebCodecsSupported'));
  assert.ok(exporterContent.includes('export async function exportMotionWebCodecs'));
  assert.ok(exporterContent.includes('export function renderCanvasFrame'));
});
