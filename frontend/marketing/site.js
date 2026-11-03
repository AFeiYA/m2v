/* Public pages never start checkout, load private projects or initialize auth. */
(() => {
  // Redirect marketing pages on www.fovea.si and mv.fovea.si to fovea.si
  if (typeof location !== 'undefined' && location.hostname) {
    const host = location.hostname.toLowerCase();
    if (host === 'www.fovea.si' || host === 'mv.fovea.si') {
      const isApp = location.pathname.startsWith('/app') || location.pathname.startsWith('/lyric-editor') || location.pathname.startsWith('/motion-studio') || location.pathname.startsWith('/motion-lab') || location.pathname.startsWith('/rhythm-studio') || location.pathname.startsWith('/gallery') || location.pathname.startsWith('/storyboard');
      if (host === 'www.fovea.si' || !isApp) {
        location.replace('https://fovea.si' + location.pathname + location.search + location.hash);
        return;
      }
    }
  }

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
  if (typeof document.querySelectorAll !== 'function') return;

  document.querySelectorAll('.hero-video-slot').forEach(slot => {
    const src = slot.getAttribute('data-example-src');
    const video = slot.querySelector('video');
    if (!src || !video || typeof fetch !== 'function') return;
    fetch(src, {method: 'HEAD'}).then(response => {
      const type = response.headers.get('content-type') || '';
      if (!response.ok || !type.startsWith('video/')) return;
      const source = video.querySelector('source');
      if (source) source.src = src;
      video.hidden = false;
      video.load();
      const live = slot.querySelector('.live-preview');
      if (live) live.hidden = true;
      slot.dataset.state = 'file';
    }).catch(() => {});
  });

  const modes = {
    apple: ['Scrolling lyrics, word by word.', 'Portrait lyrics move around the active line, with softened edges and a highlight that follows each word’s timing.', 'PORTRAIT SCROLL · 9:16'],
    karaoke: ['Two alternating lines. Timed to each word.', 'Landscape karaoke places alternating lines near the bottom of the frame. The highlight sweeps across the words as they are sung.', 'DUAL-LINE KARAOKE · 16:9'],
    poster: ['Grouped words. A complete composition.', 'Kinetic posters bring lyric groups into a shared composition. The sample uses the studio’s three-stack preset and its real entrance timing.', 'KINETIC POSTER · 9:16']
  };
  const hosts = Array.from(document.querySelectorAll('[data-preview-mode]'));
  const pending = new Map();
  let modulePromise;
  const load = host => {
    if (!pending.has(host)) {
      modulePromise ||= import('/motion/marketing-preview.js?v=20261103_convert');
      pending.set(host, modulePromise.then(module => module.mountPreview(host, host.dataset.previewMode)).catch(() => {
        host.textContent = 'Preview unavailable. Open the studio to try your song.';
        host.dataset.state = 'error';
        return null;
      }));
    }
    return pending.get(host);
  };
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => entries.forEach(entry => {
      if (entry.isIntersecting) void load(entry.target);
      else pending.get(entry.target)?.then(controller => controller?.pause());
    }), {rootMargin: '80px'});
    hosts.forEach(host => observer.observe(host));
  } else hosts.forEach(host => { void load(host); });

  const shell = document.querySelector('.demo-shell');
  if (!shell) return;
  let revision = 0, playing = false;
  const demo = shell.querySelector('[data-preview-mode]');
  const message = text => {
    const status = document.getElementById('demo-playback-status');
    if (status) status.textContent = text;
  };
  document.querySelectorAll('[data-demo]').forEach(button => button.addEventListener('click', async () => {
    const mode = button.dataset.demo;
    if (!modes[mode] || !demo) return;
    const request = ++revision;
    document.querySelectorAll('[data-demo]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
    shell.dataset.mode = mode;
    demo.dataset.previewMode = mode;
    const title = document.getElementById('demo-title');
    const description = document.getElementById('demo-description');
    if (title) title.textContent = modes[mode][0];
    if (description) description.textContent = modes[mode][1];
    const label = shell.querySelector('.demo-label');
    if (label) label.textContent = modes[mode][2];
    message('Loading sample…');
    const controller = await load(demo);
    if (request !== revision) return;
    controller?.show(mode);
    playing = false;
    message(controller ? 'Paused sample · no audio' : 'Preview unavailable');
    const replay = document.getElementById('demo-replay');
    if (replay) replay.textContent = 'Play sample ▷';
  }));
  document.getElementById('demo-replay')?.addEventListener('click', async () => {
    const controller = await load(demo);
    const replay = document.getElementById('demo-replay');
    if (!controller) { message('Preview unavailable'); return; }
    playing = !playing;
    if (playing) controller.play(); else controller.pause();
    if (replay) replay.textContent = playing ? 'Pause sample Ⅱ' : 'Play sample ▷';
    message(playing ? 'Playing sample · synthetic timing · no audio' : 'Paused sample · no audio');
  });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) return;
    playing = false;
    hosts.forEach(host => pending.get(host)?.then(controller => controller?.pause()));
    const replay = document.getElementById('demo-replay');
    if (replay) replay.textContent = 'Play sample ▷';
    message('Paused sample · no audio');
  });
})();
