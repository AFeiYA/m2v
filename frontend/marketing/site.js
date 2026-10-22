/* Public pages never start checkout, load private projects or initialize auth. */
(() => {
  // Preserve old workspace bookmarks and checkout returns without a server redirect loop.
  const workspace = new Set(['tasks-section', 'lyric-editor-section', 'motion-studio-section', 'exports-section', 'credits-section', 'settings-section']);
  if (location.pathname === '/') {
    const section = location.hash.slice(1).split('?')[0];
    const query = new URLSearchParams(location.search);
    if (workspace.has(section) || query.has('checkout') || query.has('redirect')) {
      location.replace('/app' + location.search + location.hash);
      return;
    }
  }
  const modes = {
    apple: ['Room for every line.', 'A portrait layout that keeps the current lyric in focus, with space for the lines around it.', 'PORTRAIT SCROLL · 9:16'],
    karaoke: ['Two lines. One rhythm.', 'A landscape layout with alternating lyric lines and a word-timed highlight, ready for a sing-along.', 'DUAL-LINE KARAOKE · 16:9'],
    poster: ['Words with presence.', 'A complete typographic composition, with scale, contrast and motion designed around the lyric.', 'KINETIC POSTER · 16:9 + 9:16']
  };
  const shell = document.querySelector('.demo-shell');
  if (!shell) return;
  const replay = () => {
    shell.classList.remove('replaying');
    void shell.offsetWidth;
    shell.classList.add('replaying');
  };
  document.querySelectorAll('[data-demo]').forEach(button => button.addEventListener('click', () => {
    const mode = button.dataset.demo;
    if (!modes[mode]) return;
    document.querySelectorAll('[data-demo]').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
    shell.dataset.mode = mode;
    document.getElementById('demo-title').textContent = modes[mode][0];
    document.getElementById('demo-description').textContent = modes[mode][1];
    shell.querySelector('.demo-label').textContent = modes[mode][2];
    replay();
  }));
  document.getElementById('demo-replay')?.addEventListener('click', replay);
})();
