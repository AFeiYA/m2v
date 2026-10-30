const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../local/lyric_editor.js'), 'utf8');

function setupRealignTest({ realignResponse, taskStatuses }) {
  const elements = new Map();
  const calls = [];
  const notices = [];
  let pollFn = null;
  let songLoaded = null;

  function element(selector) {
    if (!elements.has(selector)) {
      elements.set(selector, {
        style: {},
        dataset: {},
        handlers: {},
        value: '',
        textContent: '',
        disabled: false,
        addEventListener(event, fn) {
          this.handlers[event] = fn;
        },
      });
    }
    return elements.get(selector);
  }

  // Pre-seed known elements
  element('#modal-realign').style.display = 'none';
  element('#realign-edit-view').style.display = 'flex';
  element('#realign-progress-view').style.display = 'none';
  element('#realign-floating-indicator').style.display = 'none';

  let taskPollIdx = 0;

  const context = {
    window: {
      addEventListener() {},
      currentLocale: 'zh',
      m2vUserCredits: 100,
    },
    document: {
      querySelector: () => null,
      addEventListener() {},
    },
    $: element,
    $$: () => [],
    dom: {
      songSelect: { value: '1' },
    },
    state: {
      currentFile: { task_id: 'task-123', name: 'Test Song' },
      alignment: {
        lines: [
          { text: 'Old lyric line 1', words: [{ text: 'Old' }, { text: 'line' }] },
        ],
      },
    },
    loadSong: (idx) => { songLoaded = idx; },
    status: (m, isError) => notices.push({ msg: m, isError }),
    alert: (m) => notices.push({ alert: m }),
    setInterval(fn) {
      pollFn = fn;
      return 101;
    },
    clearInterval() {
      pollFn = null;
    },
    console,
  };

  context.window.apiFetch = async (url, options = {}) => {
    calls.push({ url, method: options.method, body: options.body && JSON.parse(options.body) });
    if (url.startsWith('/api/credits')) {
      return { ok: true, json: async () => ({ available: context.window.m2vUserCredits, pricing: { alignment: 20 } }) };
    }
    if (url.includes('/realign')) {
      if (realignResponse instanceof Error) throw realignResponse;
      return { ok: true, json: async () => realignResponse };
    }
    if (url.startsWith('/api/tasks/')) {
      const resp = taskStatuses[taskPollIdx] || taskStatuses[taskStatuses.length - 1];
      taskPollIdx++;
      return { ok: true, json: async () => resp };
    }
    return { ok: true, json: async () => ({}) };
  };

  vm.createContext(context);
  vm.runInContext(source, context);
  vm.runInContext('initRealignModal()', context);

  return {
    context,
    elements,
    calls,
    notices,
    openModal: () => element('#btn-realign-modal').handlers.click(),
    confirmRealign: () => element('#btn-confirm-realign').handlers.click(),
    cancelRealign: () => element('#btn-cancel-realign').handlers.click(),
    backgroundRealign: () => element('#btn-bg-realign').handlers.click(),
    clickFloating: () => element('#realign-floating-indicator').handlers.click(),
    poll: () => pollFn && pollFn(),
    hasActivePoll: () => Boolean(pollFn),
    getSongLoaded: () => songLoaded,
  };
}

test('realign modal: unchanged lyrics closes modal and notifies 0 credits', async () => {
  const env = setupRealignTest({
    realignResponse: { status: 'unchanged', cost_credits: 0 },
    taskStatuses: [],
  });

  env.openModal();
  assert.equal(env.elements.get('#modal-realign').style.display, 'flex');
  assert.equal(env.elements.get('#realign-lyrics-input').value, 'Old line');

  // Submit unchanged
  await env.confirmRealign();

  // Modal closed, 0 credit status message shown
  assert.equal(env.elements.get('#modal-realign').style.display, 'none');
  assert.equal(env.hasActivePoll(), false);
  assert.ok(env.notices.some(n => n.msg && n.msg.includes('无需重新对齐')));
  assert.equal(env.context.window.m2vUserCredits, 100);
});

test('realign modal: modified lyrics switches to progress view, polls task, and updates timestamps on completion', async () => {
  const env = setupRealignTest({
    realignResponse: { status: 'processing', task_id: 'task-123', cost_credits: 20 },
    taskStatuses: [
      { status: 'processing', current_step: 'aligning', progress: 0.5 },
      { status: 'completed', current_step: 'saving', progress: 1.0, title: 'Test Song' },
    ],
  });

  env.openModal();
  env.elements.get('#realign-lyrics-input').value = 'New lyrics line here';

  await env.confirmRealign();

  // Should have deducted 20 credits locally
  assert.equal(env.context.window.m2vUserCredits, 80);

  // Modal should switch to progress view and show floating card
  assert.equal(env.elements.get('#realign-edit-view').style.display, 'none');
  assert.equal(env.elements.get('#realign-progress-view').style.display, 'flex');
  assert.equal(env.elements.get('#realign-floating-indicator').style.display, 'flex');
  assert.equal(env.hasActivePoll(), true);

  // First poll tick: in progress
  await env.poll();
  assert.equal(env.elements.get('#realign-progress-bar-fill').style.width, '50%');
  assert.equal(env.elements.get('#realign-progress-percent').textContent, '50%');

  // Second poll tick: completed
  await env.poll();
  assert.equal(env.elements.get('#realign-progress-bar-fill').style.width, '100%');
  assert.equal(env.elements.get('#realign-progress-percent').textContent, '100%');
  assert.ok(env.elements.get('#realign-progress-step-text').textContent.includes('对齐完成'));
  assert.equal(env.hasActivePoll(), false);
  assert.equal(env.getSongLoaded(), 1);
});

test('realign modal: background button hides modal while floating card continues progress', async () => {
  const env = setupRealignTest({
    realignResponse: { status: 'processing', task_id: 'task-123', cost_credits: 20 },
    taskStatuses: [
      { status: 'processing', current_step: 'aligning', progress: 0.3 },
    ],
  });

  env.openModal();
  env.elements.get('#realign-lyrics-input').value = 'Changed line';
  await env.confirmRealign();

  // User clicks "Run in background"
  env.backgroundRealign();
  assert.equal(env.elements.get('#modal-realign').style.display, 'none');
  assert.equal(env.elements.get('#realign-floating-indicator').style.display, 'flex');

  // User clicks floating card to bring modal back
  env.clickFloating();
  assert.equal(env.elements.get('#modal-realign').style.display, 'flex');
  assert.equal(env.elements.get('#realign-progress-view').style.display, 'flex');
});

test('realign modal: handles task failure gracefully with error notification', async () => {
  const env = setupRealignTest({
    realignResponse: { status: 'processing', task_id: 'task-123', cost_credits: 20 },
    taskStatuses: [
      { status: 'failed', error_message: 'Audio separation failed' },
    ],
  });

  env.openModal();
  env.elements.get('#realign-lyrics-input').value = 'Changed line';
  await env.confirmRealign();

  await env.poll();
  assert.equal(env.hasActivePoll(), false);
  assert.ok(env.elements.get('#realign-progress-step-text').textContent.includes('Audio separation failed'));
  assert.equal(env.elements.get('#realign-progress-bar-fill').style.background, '#f43f5e');
});
