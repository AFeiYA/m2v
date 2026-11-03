/* Public pages never start checkout, load private projects or initialize auth. */
(() => {
  // Preserve old workspace bookmarks and checkout returns without a server redirect loop.
  const workspace = new Set(['tasks-section', 'lyric-editor-section', 'motion-studio-section', 'exports-section', 'credits-section', 'settings-section']);
  if (location.pathname === '/') {
    const section = location.hash.slice(1).split('?')[0];
    const query = new URLSearchParams(location.search);
    if (workspace.has(section) || query.has('checkout') || query.has('_ptxn') || query.has('redirect')) {
      location.replace('/app' + location.search + location.hash);
      return;
    }
  }
  const modes = {
    apple: {
      title: 'Scrolling lyrics, word by word.',
      desc: 'Portrait lyrics move around the active line, with softened edges and a highlight that follows each word’s timing.',
      label: 'PORTRAIT SCROLL · 9:16',
      aspect: '9/16',
      video: '/marketing/demos/apple-scroll.mp4',
      poster: '/marketing/demos/apple-scroll-poster.jpg'
    },
    karaoke: {
      title: 'Two alternating lines. Timed to each word.',
      desc: 'Landscape karaoke places alternating lines near the bottom of the frame. The highlight sweeps across the words as they are sung.',
      label: 'DUAL-LINE KARAOKE · 16:9',
      aspect: '16/9',
      video: '/marketing/demos/karaoke.mp4',
      poster: '/marketing/demos/karaoke-poster.jpg'
    },
    poster: {
      title: 'Grouped words. A complete composition.',
      desc: 'Kinetic posters bring lyric groups into a shared composition. The sample uses the studio’s three-stack preset and its real entrance timing.',
      label: 'KINETIC POSTER · 9:16',
      aspect: '9/16',
      video: '/marketing/demos/kinetic-poster.mp4',
      poster: '/marketing/demos/kinetic-poster-poster.jpg'
    }
  };
  const shell = document.querySelector('.demo-shell');
  if (!shell) return;
  const hosts = Array.from(document.querySelectorAll('[data-preview-mode]'));
  const pending = new Map();
  let modulePromise, revision = 0, playing = false;
  const message = text => {
    const el = document.getElementById('demo-playback-status');
    if (el) el.textContent = text;
  };

  const videoEl = document.getElementById('demo-video-el');
  const videoSrc = document.getElementById('demo-video-src');
  const videoContainer = document.getElementById('demo-video-container');
  const soundToggle = document.getElementById('demo-sound-toggle');
  const soundBtn = document.getElementById('demo-sound-btn');
  const demoCanvas = shell.querySelector('.demo-canvas');
  let hasVideoSource = false;

  const updateSoundUI = () => {
    if (!videoEl) return;
    const isMuted = videoEl.muted;
    if (soundToggle) {
      soundToggle.innerHTML = `<span class="sound-icon" aria-hidden="true">${isMuted ? '🔇' : '🔊'}</span><span class="sound-label">${isMuted ? 'Sound on' : 'Sound off'}</span>`;
    }
    if (soundBtn) {
      soundBtn.innerHTML = `${isMuted ? 'Turn sound on' : 'Mute sound'} <span aria-hidden="true">${isMuted ? '🔊' : '🔇'}</span>`;
    }
  };

  const load = host => {
    if (!pending.has(host)) {
      modulePromise ||= import('/motion/marketing-preview.js?v=20261022_actual_renderer');
      pending.set(host, modulePromise.then(module => module.mountPreview(host, host.dataset.previewMode)).catch(() => {
        host.textContent = 'Preview unavailable. Open the studio to try your song.';
        host.dataset.state = 'error';
        return null;
      }));
    }
    return pending.get(host);
  };

  const switchMode = async mode => {
    const info = modes[mode];
    if (!info) return;
    const request = ++revision;
    document.querySelectorAll('[data-demo]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.demo === mode)));
    shell.dataset.mode = mode;
    if (demoCanvas) demoCanvas.dataset.previewMode = mode;
    document.getElementById('demo-title').textContent = info.title;
    document.getElementById('demo-description').textContent = info.desc;
    const labelEl = shell.querySelector('.demo-label');
    if (labelEl) labelEl.textContent = info.label;

    if (videoEl && info.video) {
      videoEl.style.display = 'block';
      if (demoCanvas) demoCanvas.style.display = 'none';
      videoEl.poster = info.poster || '';
      videoEl.src = info.video;
      videoEl.load();
      const playPromise = videoEl.play();
      if (playPromise !== undefined) {
        playPromise.then(() => {
          playing = true;
          const replayBtn = document.getElementById('demo-replay');
          if (replayBtn) replayBtn.innerHTML = 'Pause video <span aria-hidden="true">Ⅱ</span>';
          message(videoEl.muted ? 'Playing video · Audio muted' : 'Playing video · Audio on');
        }).catch(() => {
          // Fallback to canvas demo if video cannot be played or file not yet available
          if (demoCanvas) {
            videoEl.style.display = 'none';
            demoCanvas.style.display = 'block';
            load(demoCanvas).then(ctrl => {
              if (request === revision) {
                ctrl?.show(mode);
                message('Paused sample · no audio');
              }
            });
          }
        });
      }
    } else if (demoCanvas) {
      if (videoEl) videoEl.style.display = 'none';
      demoCanvas.style.display = 'block';
      message('Loading sample…');
      const controller = await load(demoCanvas);
      if (request !== revision) return;
      controller?.show(mode);
      playing = false;
      message(controller ? 'Paused sample · no audio' : 'Preview unavailable');
      const replayBtn = document.getElementById('demo-replay');
      if (replayBtn) replayBtn.innerHTML = 'Play sample <span aria-hidden="true">▷</span>';
    }
  };

  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => entries.forEach(entry => {
      if (entry.isIntersecting) {
        if (entry.target === videoContainer && videoEl) {
          videoEl.play().catch(() => {});
        } else {
          void load(entry.target);
        }
      } else {
        if (entry.target === videoContainer && videoEl) {
          videoEl.pause();
        } else {
          pending.get(entry.target)?.then(controller => {
            controller?.pause();
            if (entry.target === demoCanvas) {
              playing = false;
              const replayBtn = document.getElementById('demo-replay');
              if (replayBtn) replayBtn.innerHTML = 'Play sample <span aria-hidden="true">▷</span>';
              message('Paused sample · no audio');
            }
          });
        }
      }
    }), {rootMargin:'80px'});
    hosts.forEach(host => observer.observe(host));
    if (videoContainer) observer.observe(videoContainer);
  } else {
    hosts.forEach(host => { void load(host); });
  }

  document.querySelectorAll('[data-demo]').forEach(button => {
    button.addEventListener('click', () => switchMode(button.dataset.demo));
  });

  const toggleSound = () => {
    if (!videoEl) return;
    videoEl.muted = !videoEl.muted;
    updateSoundUI();
    message(videoEl.muted ? 'Audio muted' : 'Audio playing');
  };

  soundToggle?.addEventListener('click', toggleSound);
  soundBtn?.addEventListener('click', toggleSound);

  document.getElementById('demo-replay')?.addEventListener('click', async () => {
    if (videoEl && videoEl.style.display !== 'none') {
      if (videoEl.paused) {
        videoEl.play();
        playing = true;
        document.getElementById('demo-replay').innerHTML = 'Pause video <span aria-hidden="true">Ⅱ</span>';
        message(videoEl.muted ? 'Playing video · Audio muted' : 'Playing video · Audio on');
      } else {
        videoEl.pause();
        playing = false;
        document.getElementById('demo-replay').innerHTML = 'Play video <span aria-hidden="true">▷</span>';
        message('Paused video');
      }
      return;
    }

    if (demoCanvas) {
      const controller = await load(demoCanvas);
      if (!controller) { message('Preview unavailable'); return; }
      playing = !playing;
      if (playing) controller.play(); else controller.pause();
      document.getElementById('demo-replay').innerHTML = playing ? 'Pause sample <span aria-hidden="true">Ⅱ</span>' : 'Play sample <span aria-hidden="true">▷</span>';
      message(playing ? 'Playing sample · synthetic timing · no audio' : 'Paused sample · no audio');
    }
  });

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      if (videoEl) videoEl.pause();
      playing = false;
      const replayBtn = document.getElementById('demo-replay');
      if (replayBtn) replayBtn.innerHTML = 'Play sample <span aria-hidden="true">▷</span>';
      message('Paused sample · no audio');
    }
  });

  // Attempt initial video load
  if (videoEl) {
    updateSoundUI();
    videoEl.addEventListener('error', () => {
      // Fallback to canvas preview when video file not found yet
      if (demoCanvas) {
        videoEl.style.display = 'none';
        demoCanvas.style.display = 'block';
        load(demoCanvas);
      }
    });
  }
})();
