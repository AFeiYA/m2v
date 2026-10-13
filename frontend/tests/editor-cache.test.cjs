const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function createMockIndexedDB() {
  const stores = new Map([['media', new Map()], ['projects', new Map()], ['drafts', new Map()]]);

  return {
    open: (name, version) => {
      const req = {
        onsuccess: null,
        onerror: null,
        onupgradeneeded: null,
      };

      setTimeout(() => {
        const db = {
          objectStoreNames: {
            contains: (s) => stores.has(s),
          },
          createObjectStore: (s) => {
            if (!stores.has(s)) stores.set(s, new Map());
            return {
              createIndex: () => {},
            };
          },
          transaction: (storeNames, mode) => {
            const storeName = Array.isArray(storeNames) ? storeNames[0] : storeNames;
            const storeMap = stores.get(storeName) || new Map();
            const tx = {
              oncomplete: null,
              onerror: null,
              onabort: null,
              objectStore: () => ({
                get: (key) => {
                  const getReq = { onsuccess: null, onerror: null, result: storeMap.get(key) || null };
                  setTimeout(() => getReq.onsuccess && getReq.onsuccess({ target: getReq }), 0);
                  return getReq;
                },
                put: (val) => {
                  storeMap.set(val.key, val);
                },
                delete: (key) => {
                  storeMap.delete(key);
                },
                index: () => ({
                  openCursor: (range) => {
                    const cursorReq = { onsuccess: null };
                    setTimeout(() => {
                      const entries = Array.from(storeMap.values());
                      let idx = 0;
                      function advance() {
                        if (idx < entries.length) {
                          const cur = entries[idx++];
                          cursorReq.onsuccess({
                            target: {
                              result: {
                                value: cur,
                                continue: advance,
                                delete: () => storeMap.delete(cur.key),
                              },
                            },
                          });
                        } else {
                          cursorReq.onsuccess({ target: { result: null } });
                        }
                      }
                      advance();
                    }, 0);
                    return cursorReq;
                  },
                }),
              }),
            };
            setTimeout(() => tx.oncomplete && tx.oncomplete(), 10);
            return tx;
          },
        };

        if (req.onupgradeneeded) {
          req.onupgradeneeded({ target: { result: db } });
        }
        if (req.onsuccess) {
          req.onsuccess({ target: { result: db } });
        }
      }, 0);

      return req;
    },
  };
}

function setup() {
  const source = fs.readFileSync(path.join(__dirname, '../local/cache.js'), 'utf8');
  const mockIDB = createMockIndexedDB();
  const context = {
    indexedDB: mockIDB,
    IDBKeyRange: { only: (val) => val },
    localStorage: {
      getItem: (k) => (k === 'm2v_user' ? JSON.stringify({ id: 'user_123', displayName: 'Tester' }) : null),
    },
    console,
    setTimeout,
    clearTimeout,
    Date,
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return { m2vCache: context.m2vCache };
}

test('m2vCache saves and retrieves media by version', async () => {
  const { m2vCache } = setup();
  const blob = { size: 1024, type: 'audio/mpeg' };

  await m2vCache.saveMedia('user_123', 'task_abc', 'vocals', blob, 'v1');

  // Exact version hit
  const hit = await m2vCache.getMedia('user_123', 'task_abc', 'vocals', 'v1');
  assert.equal(hit, blob);

  // Expired version miss
  const miss = await m2vCache.getMedia('user_123', 'task_abc', 'vocals', 'v2');
  assert.equal(miss, null);
});

test('m2vCache saves and checks project alignment versions', async () => {
  const { m2vCache } = setup();
  const projectData = { lines: [{ text: 'Hello' }] };

  await m2vCache.saveProject('user_123', 'task_abc', 'alignment', projectData, '100');

  const cached = await m2vCache.getProject('user_123', 'task_abc', 'alignment', '100');
  assert.deepEqual(cached, projectData);

  const stale = await m2vCache.getProject('user_123', 'task_abc', 'alignment', '200');
  assert.equal(stale, null);
});

test('m2vCache manages autosave drafts', async () => {
  const { m2vCache } = setup();
  const draftData = { lines: [{ text: 'Draft edit' }] };

  await m2vCache.saveDraft('user_123', 'task_abc', 'alignment', draftData);

  const loaded = await m2vCache.getDraft('user_123', 'task_abc', 'alignment');
  assert.ok(loaded);
  assert.deepEqual(loaded.data, draftData);

  await m2vCache.clearDraft('user_123', 'task_abc', 'alignment');
  const cleared = await m2vCache.getDraft('user_123', 'task_abc', 'alignment');
  assert.equal(cleared, null);
});

test('m2vCache clears all cached records on user logout', async () => {
  const { m2vCache } = setup();
  await m2vCache.saveMedia('user_123', 'task_1', 'vocals', { size: 50 }, '1');
  await m2vCache.saveProject('user_123', 'task_1', 'alignment', { foo: 'bar' }, '1');
  await m2vCache.saveDraft('user_123', 'task_1', 'alignment', { foo: 'bar' });

  await m2vCache.clearUserCache('user_123');

  const media = await m2vCache.getMedia('user_123', 'task_1', 'vocals', '1');
  assert.equal(media, null);
});
