const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../cast.js'), 'utf8');

function setupTestContext(characters = []) {
  const elements = new Map();
  const handlers = new Map();
  let domReadyHandler = null;

  function createElement(id, tagName = 'div') {
    return {
      id,
      tagName,
      hidden: false,
      value: '',
      innerHTML: '',
      textContent: '',
      dataset: {},
      style: {},
      classList: {
        add() {},
        remove() {},
        toggle() {},
        contains() { return false; },
      },
      addEventListener(event, fn) {
        handlers.set(`${id}:${event}`, fn);
      },
      querySelectorAll() { return []; },
      focus() {},
    };
  }

  // Pre-populate known element IDs
  [
    'cast-roster-list',
    'cast-detail-column',
    'cast-create-modal',
    'cast-search-input',
    'cast-btn-create-header',
    'cast-modal-close',
    'cast-modal-cancel',
    'cast-form-create',
    'cast-input-name',
    'cast-input-alias',
    'cast-input-age',
    'cast-input-gender',
    'cast-input-tagline',
  ].forEach(id => elements.set(id, createElement(id)));

  const mockFetch = async (url, options = {}) => {
    if (url.endsWith('/api/characters')) {
      if (options.method === 'POST') {
        const body = JSON.parse(options.body);
        return {
          ok: true,
          json: async () => ({
            id: 'char_test_123',
            identity: {
              name: body.name,
              alias: body.alias,
              age: body.age,
              gender: body.gender,
              tagline: body.tagline,
              age_locked: true,
            },
            versioning: { version: 1, is_locked: false },
            assets: { primary_image_url: '', thumbnail_url: '' },
            bound_songs: [],
          }),
        };
      }
      return {
        ok: true,
        json: async () => ({ characters }),
      };
    }
    return { ok: true, json: async () => ({ status: 'ok' }) };
  };

  const context = {
    location: { hostname: 'localhost', origin: 'http://localhost:8000' },
    localStorage: { getItem: () => null, setItem: () => {} },
    document: {
      getElementById: (id) => elements.get(id) || createElement(id),
      querySelectorAll: (sel) => {
        if (sel.includes('.cast-card')) return [];
        return [];
      },
      addEventListener: (evt, fn) => {
        if (evt === 'DOMContentLoaded') domReadyHandler = fn;
      },
    },
    fetch: mockFetch,
    window: {},
    FormData: class FormData {
      append() {}
    },
    alert() {},
    confirm: () => true,
  };

  vm.runInNewContext(source, context);
  if (domReadyHandler) domReadyHandler();

  return { context, elements, handlers };
}

test('Cast Studio initializes and registers m2vCastStudio on window', () => {
  const { context } = setupTestContext();
  assert.ok(context.window.m2vCastStudio);
  assert.equal(typeof context.window.m2vCastStudio.load, 'function');
  assert.equal(typeof context.window.m2vCastStudio.init, 'function');
});

test('Cast Studio loads and renders characters roster and detail', async () => {
  const mockChars = [
    {
      id: 'char_zero_soe_0618',
      user_id: 'system',
      visibility: 'public',
      is_official: true,
      identity: {
        name: 'Zero.SOE',
        alias: '零度',
        age: 16,
        age_locked: true,
        gender: 'female',
        tagline: 'Virtual singer from neon district',
      },
      versioning: { version: 1, is_locked: true, confirmed_at: '2026-10-25T00:00:00Z' },
      assets: { primary_image_url: '/api/characters/char_zero_soe_0618/assets/ref.png', thumbnail_url: '' },
      bound_songs: ['neon_city_echoes'],
    },
  ];

  const { context, elements } = setupTestContext(mockChars);
  await context.window.m2vCastStudio.load();

  const rosterEl = elements.get('cast-roster-list');
  assert.ok(rosterEl.innerHTML.includes('Zero.SOE'));
  assert.ok(rosterEl.innerHTML.includes('🌐 Official'));
  assert.ok(rosterEl.innerHTML.includes('16 y/o 🔒'));
  assert.ok(rosterEl.innerHTML.includes('v1 Locked'));
  assert.ok(rosterEl.innerHTML.includes('1 song'));

  const detailEl = elements.get('cast-detail-column');
  assert.ok(detailEl.innerHTML.includes('Official Benchmark Artist'));
  assert.ok(detailEl.innerHTML.includes('Reference Portrait'));
  assert.ok(detailEl.innerHTML.includes('Baseline Version Lock'));
  assert.ok(detailEl.innerHTML.includes('Song Project Binding'));
  assert.ok(detailEl.innerHTML.includes('neon_city_echoes'));
});
