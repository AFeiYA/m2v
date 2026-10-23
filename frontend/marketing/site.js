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
    apple: ['Scrolling lyrics, word by word.', 'Portrait lyrics move around the active line, with softened edges and a highlight that follows each word’s timing.', 'PORTRAIT SCROLL · 9:16'],
    karaoke: ['Two alternating lines. Timed to each word.', 'Landscape karaoke places alternating lines near the bottom of the frame. The highlight sweeps across the words as they are sung.', 'DUAL-LINE KARAOKE · 16:9'],
    poster: ['Grouped words. A complete composition.', 'Kinetic posters bring lyric groups into a shared composition. The sample uses the studio’s three-stack preset and its real entrance timing.', 'KINETIC POSTER · 9:16']
  };
  const shell = document.querySelector('.demo-shell');
  if (!shell) return;
  const hosts = Array.from(document.querySelectorAll('[data-preview-mode]'));
  const pending = new Map();
  let modulePromise, revision = 0, playing = false;
  const message = text => { document.getElementById('demo-playback-status').textContent = text; };
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
  if ('IntersectionObserver' in window) {
    const observer = new IntersectionObserver(entries => entries.forEach(entry => {
      if (entry.isIntersecting) void load(entry.target);
      else pending.get(entry.target)?.then(controller => {
        controller?.pause();
        if (entry.target === demo) {
          playing = false;
          document.getElementById('demo-replay').textContent = 'Play sample ▷';
          message('Paused sample · no audio');
        }
      });
    }), {rootMargin:'80px'});
    hosts.forEach(host => observer.observe(host));
  } else hosts.forEach(host => { void load(host); });
  const demo = shell.querySelector('[data-preview-mode]');
  document.querySelectorAll('[data-demo]').forEach(button => button.addEventListener('click', async () => {
    const mode = button.dataset.demo;
    if (!modes[mode]) return;
    const request = ++revision;
    document.querySelectorAll('[data-demo]').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
    shell.dataset.mode = mode;
    demo.dataset.previewMode = mode;
    document.getElementById('demo-title').textContent = modes[mode][0];
    document.getElementById('demo-description').textContent = modes[mode][1];
    shell.querySelector('.demo-label').textContent = modes[mode][2];
    message('Loading sample…');
    const controller = await load(demo);
    if (request !== revision) return;
    controller?.show(mode);
    playing = false;
    message(controller ? 'Paused sample · no audio' : 'Preview unavailable');
    document.getElementById('demo-replay').textContent = 'Play sample ▷';
  }));
  document.getElementById('demo-replay')?.addEventListener('click', async () => {
    const controller = await load(demo);
    if (!controller) { message('Preview unavailable'); return; }
    playing = !playing;
    if (playing) controller.play(); else controller.pause();
    document.getElementById('demo-replay').textContent = playing ? 'Pause sample Ⅱ' : 'Play sample ▷';
    message(playing ? 'Playing sample · synthetic timing · no audio' : 'Paused sample · no audio');
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      playing = false;
      document.getElementById('demo-replay').textContent = 'Play sample ▷';
      message('Paused sample · no audio');
    }
  });
})();
