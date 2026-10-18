/* Navigation only: data loading, authentication and editor state stay in dashboard.js. */
(() => {
  const pages = new Set(['tasks-section', 'exports-section', 'upload-section', 'trash-section', 'credits-section']);
  document.addEventListener('DOMContentLoaded', () => {
    const app = document.getElementById('app');
    const menu = document.getElementById('workspace-menu');
    const search = document.getElementById('song-search');
    if (window.matchMedia('(max-width: 700px)').matches) {
      app.classList.add('navigation-collapsed');
      menu.setAttribute('aria-expanded', 'false');
    }
    function navigate(focus = false) {
      const requested = location.hash.slice(1);
      const active = pages.has(requested) ? requested : 'tasks-section';
      document.querySelectorAll('.workspace-page').forEach(page => { page.hidden = page.id !== active; });
      document.querySelectorAll('[data-workspace-link]').forEach(link => {
        if (link.getAttribute('href') === '#' + active) link.setAttribute('aria-current', 'page');
        else link.removeAttribute('aria-current');
      });
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
    menu.addEventListener('click', () => {
      const collapsed = app.classList.toggle('navigation-collapsed');
      menu.setAttribute('aria-expanded', String(!collapsed));
    });
    search.addEventListener('input', () => {
      if (location.hash !== '#tasks-section') location.hash = 'tasks-section';
    });
    navigate();
  });
})();
