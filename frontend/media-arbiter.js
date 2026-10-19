/**
 * Suno2MV — Media Arbiter & Unified Playback Control
 * Guarantees audio mutual exclusion across studios (Lyric Editor vs Motion Studio)
 * and provides a shared in-memory media buffer/URL cache.
 */
(() => {
  function getSafeOrigin() {
    if (typeof window !== 'undefined' && window.location && window.location.origin) {
      return window.location.origin;
    }
    return '*';
  }

  class MediaArbiter {
    constructor() {
      this.activeSource = null; // 'lyric' | 'motion' | null
      this.listeners = new Set();
      this.mediaCache = new Map(); // key: `${songId}:${trackType}` -> { url, blob, createdAt }
      this._boundMessageHandler = this._handleMessage.bind(this);
      this._bindEvents();
    }

    _bindEvents() {
      if (typeof window === 'undefined' || typeof window.addEventListener !== 'function') return;
      window.addEventListener('message', this._boundMessageHandler);
    }

    _handleMessage(event) {
      if (typeof window !== 'undefined' && window.location?.origin && event.origin !== window.location.origin && window.location.origin !== 'null') {
        return;
      }
      const data = event.data;
      if (!data || typeof data !== 'object') return;

      if (data.type === 'M2V_MEDIA_PLAY') {
        this.requestPlay(data.source);
      } else if (data.type === 'M2V_MEDIA_PAUSE') {
        if (this.activeSource === data.source) {
          this.activeSource = null;
          this._notify('pause', { source: data.source });
        }
      }
    }

    /**
     * Request exclusive playback for a given source ('lyric' or 'motion').
     * Automatically pauses the other studio if currently active.
     */
    requestPlay(source) {
      if (!source) return;
      const previous = this.activeSource;
      if (previous && previous !== source) {
        if (previous === 'lyric') {
          this._pauseStudio('lyric');
        } else if (previous === 'motion') {
          this._pauseStudio('motion');
        }
      }
      this.activeSource = source;
      this._notify('play', { source, previous });
    }

    _pauseStudio(studioName) {
      if (typeof window !== 'undefined' && window.m2vStudios) {
        try {
          if (studioName === 'lyric') window.m2vStudios.lyric?.pause();
          if (studioName === 'motion') window.m2vStudios.motion?.pause();
        } catch (_) {}
      }
    }

    /**
     * Pause all active media across all studios.
     */
    pauseAll() {
      this._pauseStudio('lyric');
      this._pauseStudio('motion');
      const prev = this.activeSource;
      this.activeSource = null;
      if (prev) {
        this._notify('pause', { source: 'all', previous: prev });
      }
    }

    /**
     * Subscribe to playback arbiter events ('play', 'pause').
     */
    subscribe(callback) {
      if (typeof callback === 'function') {
        this.listeners.add(callback);
        return () => this.listeners.delete(callback);
      }
      return () => {};
    }

    _notify(event, data) {
      for (const listener of this.listeners) {
        try {
          listener(event, data);
        } catch (e) {
          if (typeof console !== 'undefined') console.error('[MediaArbiter] Listener error:', e);
        }
      }
    }

    // ---------------- Shared Media Resource Cache ----------------

    getCachedMedia(songId, trackType = 'original') {
      if (!songId) return null;
      const key = `${songId}:${trackType}`;
      return this.mediaCache.get(key) || null;
    }

    cacheMedia(songId, trackType = 'original', entry = {}) {
      if (!songId) return;
      const key = `${songId}:${trackType}`;
      const record = {
        url: entry.url || null,
        blob: entry.blob || null,
        createdAt: Date.now(),
      };
      this.mediaCache.set(key, record);
      return record;
    }

    revokeMedia(songId = null) {
      for (const [key, item] of this.mediaCache.entries()) {
        if (!songId || key.startsWith(`${songId}:`)) {
          if (item?.url && typeof item.url === 'string' && item.url.startsWith('blob:')) {
            try {
              if (typeof URL !== 'undefined' && typeof URL.revokeObjectURL === 'function') {
                URL.revokeObjectURL(item.url);
              }
            } catch (_) {}
          }
          this.mediaCache.delete(key);
        }
      }
    }

    clearAll() {
      this.pauseAll();
      this.revokeMedia();
    }
  }

  const m2vMediaArbiter = new MediaArbiter();

  if (typeof window !== 'undefined') {
    window.m2vMediaArbiter = m2vMediaArbiter;
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { MediaArbiter, m2vMediaArbiter };
  }
})();
