/**
 * M2V IndexedDB Local-First Caching Layer
 * Provides persistent storage for audio blobs (vocals, instrumental, original),
 * alignment project JSON, and local auto-save drafts.
 * Keyed by: uid + taskId + fileType + version.
 */
(function (global) {
  "use strict";

  const DB_NAME = "m2v_editor_cache";
  const DB_VERSION = 1;
  const MAX_MEDIA_CACHE_BYTES = 500 * 1024 * 1024; // 500 MB LRU limit

  let dbPromise = null;

  function openDatabase() {
    if (dbPromise) return dbPromise;
    dbPromise = new Promise((resolve, reject) => {
      if (typeof indexedDB === "undefined") {
        return reject(new Error("IndexedDB 不受当前环境支持"));
      }

      const request = indexedDB.open(DB_NAME, DB_VERSION);

      request.onupgradeneeded = (event) => {
        const db = event.target.result;

        // 1. Media tracks (blobs)
        if (!db.objectStoreNames.contains("media")) {
          const mediaStore = db.createObjectStore("media", { keyPath: "key" });
          mediaStore.createIndex("by_uid", "uid", { unique: false });
          mediaStore.createIndex("by_lastUsed", "lastUsedAt", { unique: false });
        }

        // 2. Projects (alignment JSON, director plans)
        if (!db.objectStoreNames.contains("projects")) {
          const projectStore = db.createObjectStore("projects", { keyPath: "key" });
          projectStore.createIndex("by_uid", "uid", { unique: false });
        }

        // 3. Drafts (local unsaved edits)
        if (!db.objectStoreNames.contains("drafts")) {
          const draftStore = db.createObjectStore("drafts", { keyPath: "key" });
          draftStore.createIndex("by_uid", "uid", { unique: false });
        }
      };

      request.onsuccess = (event) => resolve(event.target.result);
      request.onerror = (event) => reject(event.target.error);
    });
    return dbPromise;
  }

  function getCompositeKey(uid, taskId, type) {
    const safeUid = uid || "anon";
    const safeTask = taskId || "default";
    const safeType = type || "data";
    return `${safeUid}:${safeTask}:${safeType}`;
  }

  function getCurrentUid() {
    try {
      const userStr = localStorage.getItem("m2v_user");
      if (userStr) {
        const user = JSON.parse(userStr);
        if (user && user.id) return user.id;
        if (user && user.uid) return user.uid;
      }
    } catch (_) {}

    if (typeof firebase !== "undefined" && firebase.auth && firebase.auth().currentUser) {
      return firebase.auth().currentUser.uid;
    }
    return "anon";
  }

  /**
   * Safe promise wrapper for IDB transaction
   */
  async function performTransaction(storeName, mode, callback) {
    const db = await openDatabase();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(storeName, mode);
      const store = tx.objectStore(storeName);

      let reqResult = null;
      try {
        reqResult = callback(store, tx);
      } catch (err) {
        reject(err);
        return;
      }

      tx.oncomplete = () => resolve(reqResult);
      tx.onerror = (e) => reject(e.target.error);
      tx.onabort = (e) => reject(e.target.error);
    });
  }

  const m2vCache = {
    getCurrentUid,

    /**
     * 读取缓存的媒体 Blob (人声/伴奏/原曲)
     */
    async getMedia(uid, taskId, type, expectedVersion) {
      if (!taskId) return null;
      const key = getCompositeKey(uid || getCurrentUid(), taskId, type);

      try {
        const db = await openDatabase();
        return await new Promise((resolve) => {
          const tx = db.transaction("media", "readwrite");
          const store = tx.objectStore("media");
          const req = store.get(key);

          req.onsuccess = () => {
            const record = req.result;
            if (!record || !record.blob) {
              resolve(null);
              return;
            }
            if (expectedVersion && String(record.version) !== String(expectedVersion)) {
              console.log(`[m2vCache] 媒体缓存版本失效 (${type}): 本地=${record.version}, 远端=${expectedVersion}`);
              resolve(null);
              return;
            }
            // 更新最后使用时间
            record.lastUsedAt = Date.now();
            store.put(record);
            resolve(record.blob);
          };

          req.onerror = () => resolve(null);
        });
      } catch (e) {
        console.warn("[m2vCache] 读取媒体失败:", e);
        return null;
      }
    },

    /**
     * 写入媒体 Blob
     */
    async saveMedia(uid, taskId, type, blob, version) {
      if (!taskId || !blob) return false;
      const effectiveUid = uid || getCurrentUid();
      const key = getCompositeKey(effectiveUid, taskId, type);

      try {
        const record = {
          key,
          uid: effectiveUid,
          taskId,
          type,
          version: version ? String(version) : "1",
          blob,
          mimeType: blob.type || "audio/mpeg",
          size: blob.size || 0,
          updatedAt: Date.now(),
          lastUsedAt: Date.now(),
        };

        await performTransaction("media", "readwrite", (store) => {
          store.put(record);
        });

        // 异步检查并修剪空间
        setTimeout(() => m2vCache.pruneMediaCache(), 1000);
        return true;
      } catch (e) {
        console.warn("[m2vCache] 写入媒体缓存失败:", e);
        return false;
      }
    },

    /**
     * 读取项目 JSON (对齐数据或分镜)
     */
    async getProject(uid, taskId, type = "alignment", expectedVersion = null) {
      if (!taskId) return null;
      const key = getCompositeKey(uid || getCurrentUid(), taskId, type);

      try {
        const db = await openDatabase();
        return await new Promise((resolve) => {
          const tx = db.transaction("projects", "readwrite");
          const store = tx.objectStore("projects");
          const req = store.get(key);

          req.onsuccess = () => {
            const record = req.result;
            if (!record || !record.data) {
              resolve(null);
              return;
            }
            if (expectedVersion && String(record.version) !== String(expectedVersion)) {
              console.log(`[m2vCache] 项目数据版本过期 (${type}): 本地=${record.version}, 远端=${expectedVersion}`);
              resolve(null);
              return;
            }
            record.lastUsedAt = Date.now();
            store.put(record);
            resolve(record.data);
          };

          req.onerror = () => resolve(null);
        });
      } catch (e) {
        console.warn("[m2vCache] 读取项目缓存失败:", e);
        return null;
      }
    },

    /**
     * 保存项目 JSON
     */
    async saveProject(uid, taskId, type = "alignment", data, version = null) {
      if (!taskId || !data) return false;
      const effectiveUid = uid || getCurrentUid();
      const key = getCompositeKey(effectiveUid, taskId, type);

      try {
        const record = {
          key,
          uid: effectiveUid,
          taskId,
          type,
          version: version ? String(version) : "1",
          data,
          updatedAt: Date.now(),
          lastUsedAt: Date.now(),
        };

        await performTransaction("projects", "readwrite", (store) => {
          store.put(record);
        });
        return true;
      } catch (e) {
        console.warn("[m2vCache] 写入项目缓存失败:", e);
        return false;
      }
    },

    /**
     * 获取未保存本地草稿
     */
    async getDraft(uid, taskId, type = "alignment") {
      if (!taskId) return null;
      const key = getCompositeKey(uid || getCurrentUid(), taskId, type);

      try {
        const db = await openDatabase();
        return await new Promise((resolve) => {
          const tx = db.transaction("drafts", "readonly");
          const store = tx.objectStore("drafts");
          const req = store.get(key);
          req.onsuccess = () => resolve(req.result || null);
          req.onerror = () => resolve(null);
        });
      } catch (e) {
        return null;
      }
    },

    /**
     * 保存本地草稿
     */
    async saveDraft(uid, taskId, type = "alignment", data) {
      if (!taskId || !data) return false;
      const effectiveUid = uid || getCurrentUid();
      const key = getCompositeKey(effectiveUid, taskId, type);

      try {
        const record = {
          key,
          uid: effectiveUid,
          taskId,
          type,
          data,
          savedAt: Date.now(),
        };
        await performTransaction("drafts", "readwrite", (store) => {
          store.put(record);
        });
        return true;
      } catch (e) {
        console.warn("[m2vCache] 保存草稿失败:", e);
        return false;
      }
    },

    /**
     * 清理草稿（保存成功或放弃后）
     */
    async clearDraft(uid, taskId, type = "alignment") {
      if (!taskId) return;
      const key = getCompositeKey(uid || getCurrentUid(), taskId, type);
      try {
        await performTransaction("drafts", "readwrite", (store) => {
          store.delete(key);
        });
      } catch (_) {}
    },

    /**
     * 用户退出登录时清理该 UID 下的全部缓存
     */
    async clearUserCache(uid) {
      const targetUid = uid || getCurrentUid();
      if (!targetUid) return;

      try {
        const db = await openDatabase();
        const stores = ["media", "projects", "drafts"];
        await Promise.all(
          stores.map((storeName) => {
            return new Promise((resolve, reject) => {
              const tx = db.transaction(storeName, "readwrite");
              const store = tx.objectStore(storeName);
              const index = store.index("by_uid");
              const range = typeof IDBKeyRange !== "undefined" && IDBKeyRange.only ? IDBKeyRange.only(targetUid) : null;
              const req = index.openCursor(range);
              req.onsuccess = (e) => {
                const cursor = e.target.result;
                if (cursor) {
                  cursor.delete();
                  cursor.continue();
                }
              };
              tx.oncomplete = () => resolve();
              tx.onerror = (err) => reject(err);
              tx.onabort = (err) => reject(err);
            });
          })
        );
        console.log(`[m2vCache] 已清空用户 ${targetUid} 的本地缓存与草稿`);
      } catch (e) {
        console.warn("[m2vCache] 清理用户缓存失败:", e);
      }
    },

    /**
     * 空间不足或达到容量限制时，LRU 淘汰旧媒体
     */
    async pruneMediaCache(maxBytes = MAX_MEDIA_CACHE_BYTES) {
      try {
        const db = await openDatabase();
        const tx = db.transaction("media", "readwrite");
        const store = tx.objectStore("media");
        const index = store.index("by_lastUsed");

        const items = [];
        let totalSize = 0;

        const req = index.openCursor(); // 默认升序：最久未使用的在最前
        req.onsuccess = (e) => {
          const cursor = e.target.result;
          if (cursor) {
            const val = cursor.value;
            const size = val.size || (val.blob ? val.blob.size : 0) || 0;
            totalSize += size;
            items.push({ key: val.key, size, lastUsedAt: val.lastUsedAt });
            cursor.continue();
          } else {
            // 扫描完毕，检查是否超出阈值
            if (totalSize > maxBytes) {
              let toFree = totalSize - maxBytes;
              for (const item of items) {
                if (toFree <= 0) break;
                store.delete(item.key);
                toFree -= item.size;
                console.log(`[m2vCache] LRU 清理旧音轨缓存: ${item.key} (${Math.round(item.size / 1024)} KB)`);
              }
            }
          }
        };
      } catch (e) {
        console.warn("[m2vCache] 空间清理失败:", e);
      }
    },
  };

  global.m2vCache = m2vCache;
})(typeof window !== "undefined" ? window : globalThis);
