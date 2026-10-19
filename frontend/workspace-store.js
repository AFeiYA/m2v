/**
 * Suno2MV — Single Source of Truth (SSOT) Workspace Store
 * Manages account, active song, lyric version, motion project, and dirty state.
 */
(() => {
  class WorkspaceStore {
    constructor() {
      this._state = {
        account: {
          user: null,
          provider: null,
          isAuthenticated: false,
        },
        song: {
          activeSong: null,       // { id, title, artist, ... }
          activeVersionId: null,  // version/task id currently being edited
          savedVersion: null,     // server version tag or commit hash
          isDirty: false,         // has unsaved changes
        },
        motion: {
          activeProjectId: null,
          preset: null,
        },
        navigation: {
          activeSection: 'tasks-section',
          activeStudio: 'library', // 'library' | 'lyric' | 'motion' | 'exports'
        }
      };

      this._subscribers = new Set();
      this._initFromStorage();
    }

    _initFromStorage() {
      try {
        if (typeof localStorage !== 'undefined') {
          const userStr = localStorage.getItem('m2v_user');
          const provider = localStorage.getItem('m2v_auth_provider');
          const token = localStorage.getItem('m2v_token');
          if (userStr && token) {
            this._state.account.user = JSON.parse(userStr);
            this._state.account.provider = provider;
            this._state.account.isAuthenticated = true;
          }
        }
        if (typeof sessionStorage !== 'undefined') {
          const songStr = sessionStorage.getItem('m2v_active_song');
          if (songStr) {
            const song = JSON.parse(songStr);
            this._state.song.activeSong = song;
            this._state.song.activeVersionId = song.id || null;
          }
        }
      } catch (_) {}
    }

    getState() {
      return this._state;
    }

    subscribe(fn) {
      if (typeof fn === 'function') {
        this._subscribers.add(fn);
        return () => this._subscribers.delete(fn);
      }
      return () => {};
    }

    _notify(action, payload) {
      for (const listener of this._subscribers) {
        try {
          listener(this._state, action, payload);
        } catch (e) {
          console.error('[m2vStore] listener error:', e);
        }
      }
    }

    setUser(user, provider) {
      this._state.account.user = user;
      this._state.account.provider = provider;
      this._state.account.isAuthenticated = Boolean(user);
      this._notify('USER_CHANGED', { user, provider });
    }

    clearUser() {
      this._state.account.user = null;
      this._state.account.provider = null;
      this._state.account.isAuthenticated = false;
      this.clearSong();
      this._notify('USER_LOGOUT', null);
    }

    setActiveSong(song) {
      if (!song) {
        this.clearSong();
        return;
      }
      const prevId = this._state.song.activeSong?.id;
      this._state.song.activeSong = {
        id: song.id,
        title: song.title || song.id,
        artist: song.artist || '',
      };
      this._state.song.activeVersionId = song.versionId || song.id;
      if (prevId !== song.id) {
        this._state.song.isDirty = false;
        this._state.song.savedVersion = null;
      }
      try {
        if (typeof sessionStorage !== 'undefined') {
          sessionStorage.setItem('m2v_active_song', JSON.stringify(this._state.song.activeSong));
        }
      } catch (_) {}
      this._notify('SONG_CHANGED', this._state.song.activeSong);
    }

    setLyricVersion(versionId, savedVersion = null) {
      this._state.song.activeVersionId = versionId;
      if (savedVersion !== null) this._state.song.savedVersion = savedVersion;
      this._notify('VERSION_CHANGED', { versionId, savedVersion });
    }

    setDirty(isDirty) {
      if (this._state.song.isDirty !== Boolean(isDirty)) {
        this._state.song.isDirty = Boolean(isDirty);
        this._notify('DIRTY_CHANGED', this._state.song.isDirty);
      }
    }

    clearSong() {
      this._state.song.activeSong = null;
      this._state.song.activeVersionId = null;
      this._state.song.savedVersion = null;
      this._state.song.isDirty = false;
      this._state.motion.activeProjectId = null;
      try {
        if (typeof sessionStorage !== 'undefined') {
          sessionStorage.removeItem('m2v_active_song');
        }
      } catch (_) {}
      this._notify('SONG_CLEARED', null);
    }

    setActiveSection(section) {
      this._state.navigation.activeSection = section;
      const studioMap = {
        'tasks-section': 'library',
        'lyric-editor-section': 'lyric',
        'motion-studio-section': 'motion',
        'exports-section': 'exports',
      };
      this._state.navigation.activeStudio = studioMap[section] || 'library';
      this._notify('NAVIGATION_CHANGED', this._state.navigation);
    }
  }

  const store = new WorkspaceStore();
  if (typeof window !== 'undefined') {
    window.m2vStore = store;
  }
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { WorkspaceStore, store };
  }
})();
