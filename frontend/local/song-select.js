/** Load every library page for the native song dropdown, using the caller's authenticated API. */
(function () {
  function account() {
    return localStorage.getItem('m2v_user') || localStorage.getItem('m2v_token') || '';
  }
  async function load(request) {
    const owner = account(), songs = [], seen = new Set();
    for (let page = 1; ; page++) {
      const data = await request('/api/songs?view=all&page_size=50&page=' + page);
      if (owner !== account()) throw Error('Account changed. Please reload your songs.');
      const rows = data.songs || [];
      for (const song of rows) {
        if (song.current_task_id && !seen.has(song.current_task_id)) {
          seen.add(song.current_task_id);
          songs.push(song);
        }
      }
      if (!rows.length || page * 50 >= data.total) return songs;
      if (!Number.isFinite(data.total)) throw Error('Unable to load your song library. Please retry.');
    }
  }
  window.m2vSongSelect = {load};
})();
