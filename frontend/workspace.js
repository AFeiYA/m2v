/* Navigation only: data loading, authentication and editor state stay in dashboard.js. */
(() => {
  const pages = new Set([
    'tasks-section',
    'exports-section',
    'upload-section',
    'trash-section',
    'credits-section',
    'lyric-editor-section',
    'motion-studio-section'
  ]);

  document.addEventListener('DOMContentLoaded', () => {
    const app = document.getElementById('app');
    const menu = document.getElementById('workspace-menu');
    const search = document.getElementById('song-search');
    let currentActiveSection = null;

    if (window.matchMedia('(max-width: 700px)').matches) {
      app.classList.add('navigation-collapsed');
      menu.setAttribute('aria-expanded', 'false');
    }

    function getActiveSong() {
      if (window.m2vStore) return window.m2vStore.getState().song.activeSong;
      if (window.m2vActiveSong) return window.m2vActiveSong;
      try {
        if (typeof sessionStorage !== 'undefined') {
          return JSON.parse(sessionStorage.getItem('m2v_active_song') || 'null');
        }
      } catch (_) {}
      return null;
    }

    function setActiveSong(song) {
      if (window.m2vStore) window.m2vStore.setActiveSong(song);
      window.m2vActiveSong = song;
      try {
        if (typeof sessionStorage !== 'undefined') {
          sessionStorage.setItem('m2v_active_song', JSON.stringify(song));
        }
      } catch (_) {}
    }

    function navigate(focus = false) {
      const rawHash = location.hash.slice(1);
      const [pageName, queryString] = rawHash.split('?');
      const requested = pageName;
      const active = pages.has(requested) ? requested : 'tasks-section';

      // Parse optional query params from hash like #lyric-editor-section?song=abc
      if (queryString) {
        try {
          const params = new URLSearchParams(queryString);
          const songId = params.get('song') || params.get('project');
          if (songId) {
            const currentSong = getActiveSong() || {};
            setActiveSong({ ...currentSong, id: songId });
          }
        } catch (_) {}
      }
      if (window.m2vStore) window.m2vStore.setActiveSection(active);

      const isStudio = (active === 'lyric-editor-section' || active === 'motion-studio-section');
      if (isStudio) {
        if (typeof app.classList?.add === 'function') app.classList.add('in-studio-mode');
      } else {
        if (typeof app.classList?.remove === 'function') app.classList.remove('in-studio-mode');
      }

      // Toggle page visibility
      document.querySelectorAll('.workspace-page').forEach(page => {
        page.hidden = page.id !== active;
      });

      // Update sidebar links
      document.querySelectorAll('[data-workspace-link]').forEach(link => {
        const href = link.getAttribute('href') || '';
        const target = href.replace(/^#/, '');
        if (target === active) link.setAttribute('aria-current', 'page');
        else link.removeAttribute('aria-current');
      });

      // Update header studio tabs
      document.querySelectorAll('.studio-tab-btn').forEach(btn => {
        const target = (btn.getAttribute('href') || '').replace(/^#/, '');
        if (target === active) {
          if (typeof btn.classList?.add === 'function') btn.classList.add('active');
          btn.setAttribute('aria-current', 'page');
        } else {
          if (typeof btn.classList?.remove === 'function') btn.classList.remove('active');
          btn.removeAttribute('aria-current');
        }
      });

      const titles = {
        'tasks-section': 'My Library',
        'exports-section': 'My Exports',
        'upload-section': 'New Project',
        'trash-section': 'Trash',
        'credits-section': 'Credits & Billing',
        'lyric-editor-section': 'Lyric Studio',
        'motion-studio-section': 'Motion Studio',
      };

      const bc = document.getElementById('bc-current');
      if (bc) bc.textContent = titles[active] || 'My Library';

      // Update active song display in breadcrumbs
      const activeSong = getActiveSong();
      const bcSong = document.getElementById('bc-song-name');
      const bcSepSong = document.getElementById('bc-sep-song');
      if (isStudio && activeSong?.title) {
        if (bcSong) {
          bcSong.textContent = '🎵 ' + activeSong.title;
          if (bcSong.style) bcSong.style.display = 'inline';
        }
        if (bcSepSong && bcSepSong.style) bcSepSong.style.display = 'inline';
      } else {
        if (bcSong && bcSong.style) bcSong.style.display = 'none';
        if (bcSepSong && bcSepSong.style) bcSepSong.style.display = 'none';
      }

      // Studio adapter lifecycle pause for inactive studios and media arbiter
      if (currentActiveSection === 'lyric-editor-section' && active !== 'lyric-editor-section') {
        window.m2vStudios?.lyric?.pause();
        window.m2vMediaArbiter?.pauseAll();
      } else if (currentActiveSection === 'motion-studio-section' && active !== 'motion-studio-section') {
        window.m2vStudios?.motion?.pause();
        window.m2vMediaArbiter?.pauseAll();
      } else if (active !== 'lyric-editor-section' && active !== 'motion-studio-section') {
        window.m2vMediaArbiter?.pauseAll();
      }
      currentActiveSection = active;

      // Lazy load or update studio frames
      if (active === 'lyric-editor-section') {
        window.m2vStudios?.lyric?.activate({ songId: activeSong?.id });
        const iframe = document.getElementById('iframe-lyric-editor');
        const songId = activeSong?.id || '';
        const targetSrc = songId ? `/lyric-editor/${encodeURIComponent(songId)}` : '/lyric-editor';
        if (iframe) {
          if (!iframe.src || iframe.src === 'about:blank' || iframe.dataset.loadedSongId !== songId) {
            iframe.src = targetSrc;
            iframe.dataset.loadedSongId = songId;
          } else {
            try {
              iframe.contentWindow?.postMessage({ type: 'M2V_LOAD_SONG', songId }, window.location.origin);
            } catch (_) {}
          }
        }
        const barTitle = document.getElementById('lyric-bar-song-title');
        if (barTitle && activeSong?.title) barTitle.textContent = activeSong.title;
      } else if (active === 'motion-studio-section') {
        window.m2vStudios?.motion?.activate({ songId: activeSong?.id });
        const iframe = document.getElementById('iframe-motion-studio');
        const songId = activeSong?.id || '';
        const targetSrc = songId ? `/motion-studio?project=${encodeURIComponent(songId)}` : '/motion-studio';
        if (iframe) {
          if (!iframe.src || iframe.src === 'about:blank' || iframe.dataset.loadedSongId !== songId) {
            iframe.src = targetSrc;
            iframe.dataset.loadedSongId = songId;
          } else {
            try {
              iframe.contentWindow?.postMessage({ type: 'M2V_LOAD_SONG', songId }, window.location.origin);
            } catch (_) {}
          }
        }
        const barTitle = document.getElementById('motion-bar-song-title');
        if (barTitle && activeSong?.title) barTitle.textContent = activeSong.title;
      }

      if (active === 'credits-section') window.m2vBilling?.refresh();
      if (active === 'trash-section') document.getElementById('version-trash').open = true;
      if (active !== 'exports-section') document.getElementById('btn-close-export-preview')?.click();

      if (focus) {
        if (window.matchMedia('(max-width: 700px)').matches) {
          app.classList.add('navigation-collapsed');
          menu.setAttribute('aria-expanded', 'false');
        }
        document.getElementById(active)?.focus({preventScroll: true});
      }

      // Hash anchors would otherwise scroll the section title under the sticky header.
      window.requestAnimationFrame?.(() => window.scrollTo({top: 0, left: 0, behavior: 'instant'}));
    }

    window.addEventListener('hashchange', () => navigate(true));

    // Handle cross-frame communication with embedded studios
    window.addEventListener('message', (event) => {
      if (typeof window !== 'undefined' && event.origin !== window.location.origin) return;
      if (!event.data || typeof event.data !== 'object') return;
      if (event.data.type === 'M2V_NAVIGATE') {
        const target = (event.data.hash || '').replace(/^#/, '');
        if (pages.has(target)) location.hash = target;
      } else if (event.data.type === 'M2V_SWITCH_STUDIO') {
        const target = event.data.target;
        const songId = event.data.songId;
        if (target === 'motion-studio' && window.openMotionStudio) {
          window.openMotionStudio(songId);
        } else if (target === 'lyric-editor' && window.openLyricStudio) {
          window.openLyricStudio(songId);
        }
      } else if (event.data.type === 'M2V_SONG_CHANGED') {
        const { songId, title } = event.data;
        if (songId) {
          window.m2vMediaArbiter?.pauseAll();
          window.m2vMediaArbiter?.revokeMedia();
          setActiveSong({ id: songId, title: title || songId });
          const bcSong = document.getElementById('bc-song-name');
          const bcSep = document.getElementById('bc-sep-song');
          if (bcSong) {
            bcSong.textContent = '🎵 ' + (title || songId);
            if (bcSong.style) bcSong.style.display = 'inline';
            if (bcSep && bcSep.style) bcSep.style.display = 'inline';
          }
          const lTitle = document.getElementById('lyric-bar-song-title');
          if (lTitle) lTitle.textContent = title || songId;
          const mTitle = document.getElementById('motion-bar-song-title');
          if (mTitle) mTitle.textContent = title || songId;
        }
      }
    });

    // Studio toolbar button handlers
    document.getElementById('btn-close-lyric-view')?.addEventListener('click', () => {
      location.hash = 'tasks-section';
    });
    document.getElementById('btn-close-motion-view')?.addEventListener('click', () => {
      location.hash = 'tasks-section';
    });
    document.getElementById('btn-lyric-to-motion')?.addEventListener('click', () => {
      const activeSong = getActiveSong();
      if (window.openMotionStudio) window.openMotionStudio(activeSong?.id, activeSong?.title);
      else location.hash = 'motion-studio-section';
    });
    document.getElementById('btn-motion-to-lyric')?.addEventListener('click', () => {
      const activeSong = getActiveSong();
      if (window.openLyricStudio) window.openLyricStudio(activeSong?.id, activeSong?.title);
      else location.hash = 'lyric-editor-section';
    });

    menu.addEventListener('click', () => {
      const collapsed = app.classList.toggle('navigation-collapsed');
      menu.setAttribute('aria-expanded', String(!collapsed));
    });

    search.addEventListener('input', () => {
      if (location.hash !== '#tasks-section') location.hash = 'tasks-section';
    });

    document.getElementById('btn-paste-suno')?.addEventListener('click', async () => {
      try {
        const text = await navigator.clipboard?.readText?.();
        if (text) {
          const input = document.getElementById('input-suno-url');
          if (input) { input.value = text.trim(); input.dispatchEvent(new Event('input')); }
        }
      } catch (_) {}
    });

    navigate();
  });
})();
