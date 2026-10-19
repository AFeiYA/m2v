/**
 * Suno2MV — Studio Module Adapters
 * Standardized lifecycle interface (mount, activate, pause, destroy) for studios.
 */
(() => {
  function getTargetOrigin() {
    if (typeof window !== 'undefined' && window.location && window.location.origin) {
      return window.location.origin;
    }
    return '*';
  }

  function getIframe(container, selector, id) {
    if (container && typeof container.querySelector === 'function') {
      const el = container.querySelector(selector);
      if (el) return el;
    }
    if (typeof document !== 'undefined' && typeof document.getElementById === 'function') {
      return document.getElementById(id);
    }
    return null;
  }

  class LyricStudioAdapter {
    constructor() {
      this.name = 'lyric';
      this.container = null;
      this.currentSongId = null;
    }

    async mount(container, context = {}) {
      this.container = container;
      const iframe = getIframe(container, '#iframe-lyric-editor', 'iframe-lyric-editor');
      if (iframe && context.songId) {
        this.currentSongId = context.songId;
        const targetSrc = `/lyric-editor/${encodeURIComponent(context.songId)}`;
        if (iframe.src !== targetSrc) {
          iframe.src = targetSrc;
          if (iframe.dataset) iframe.dataset.loadedSongId = context.songId;
        }
      }
    }

    async activate(context = {}) {
      const songId = context.songId || this.currentSongId;
      const iframe = getIframe(this.container, '#iframe-lyric-editor', 'iframe-lyric-editor');
      if (iframe) {
        if (songId && iframe.dataset?.loadedSongId !== songId) {
          this.currentSongId = songId;
          iframe.src = `/lyric-editor/${encodeURIComponent(songId)}`;
          if (iframe.dataset) iframe.dataset.loadedSongId = songId;
        } else if (songId) {
          try {
            iframe.contentWindow?.postMessage({ type: 'M2V_LOAD_SONG', songId }, getTargetOrigin());
          } catch (_) {}
        }
      }
    }

    pause() {
      const iframe = getIframe(this.container, '#iframe-lyric-editor', 'iframe-lyric-editor');
      if (iframe?.contentWindow) {
        try {
          iframe.contentWindow.postMessage({ type: 'M2V_STUDIO_PAUSE' }, getTargetOrigin());
        } catch (_) {}
      }
    }

    destroy() {
      const iframe = getIframe(this.container, '#iframe-lyric-editor', 'iframe-lyric-editor');
      if (iframe) {
        try {
          iframe.contentWindow?.postMessage({ type: 'M2V_STUDIO_DESTROY' }, getTargetOrigin());
        } catch (_) {}
        iframe.src = 'about:blank';
        if (iframe.dataset) delete iframe.dataset.loadedSongId;
      }
      this.currentSongId = null;
    }
  }

  class MotionStudioAdapter {
    constructor() {
      this.name = 'motion';
      this.container = null;
      this.currentSongId = null;
    }

    async mount(container, context = {}) {
      this.container = container;
      const iframe = getIframe(container, '#iframe-motion-studio', 'iframe-motion-studio');
      if (iframe && context.songId) {
        this.currentSongId = context.songId;
        const targetSrc = `/motion-studio?project=${encodeURIComponent(context.songId)}`;
        if (iframe.src !== targetSrc) {
          iframe.src = targetSrc;
          if (iframe.dataset) iframe.dataset.loadedSongId = context.songId;
        }
      }
    }

    async activate(context = {}) {
      const songId = context.songId || this.currentSongId;
      const iframe = getIframe(this.container, '#iframe-motion-studio', 'iframe-motion-studio');
      if (iframe) {
        if (songId && iframe.dataset?.loadedSongId !== songId) {
          this.currentSongId = songId;
          iframe.src = `/motion-studio?project=${encodeURIComponent(songId)}`;
          if (iframe.dataset) iframe.dataset.loadedSongId = songId;
        } else if (songId) {
          try {
            iframe.contentWindow?.postMessage({ type: 'M2V_LOAD_SONG', songId }, getTargetOrigin());
          } catch (_) {}
        }
      }
    }

    pause() {
      const iframe = getIframe(this.container, '#iframe-motion-studio', 'iframe-motion-studio');
      if (iframe?.contentWindow) {
        try {
          iframe.contentWindow.postMessage({ type: 'M2V_STUDIO_PAUSE' }, getTargetOrigin());
        } catch (_) {}
      }
    }

    destroy() {
      const iframe = getIframe(this.container, '#iframe-motion-studio', 'iframe-motion-studio');
      if (iframe) {
        try {
          iframe.contentWindow?.postMessage({ type: 'M2V_STUDIO_DESTROY' }, getTargetOrigin());
        } catch (_) {}
        iframe.src = 'about:blank';
        if (iframe.dataset) delete iframe.dataset.loadedSongId;
      }
      this.currentSongId = null;
    }
  }

  const m2vStudios = {
    lyric: new LyricStudioAdapter(),
    motion: new MotionStudioAdapter(),
  };

  if (typeof window !== 'undefined') {
    window.m2vStudios = m2vStudios;
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { LyricStudioAdapter, MotionStudioAdapter, m2vStudios };
  }
})();
