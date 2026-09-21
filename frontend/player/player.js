/* ============================================================
   M2V Player — Karaoke Engine with Gradient-Fill Light-Sweep
   ============================================================
   Auto-loads songs from server API (node server.js).
   Each song folder contains audio, alignment.json, and images/.
   ============================================================ */

(() => {
  'use strict';

  // ─── DOM refs ───
  const $ = (sel) => document.querySelector(sel);
  const btnPlay      = $('#btn-play');
  const btnPrev      = $('#btn-prev');
  const btnNext      = $('#btn-next');
  const iconPlay     = $('#icon-play');
  const iconPause    = $('#icon-pause');
  const lyricsContainer = $('#lyrics-scroll-container');
  const progressBar  = $('#progress-bar');
  const progressFill = $('#progress-fill');
  const progressGlow = $('#progress-glow');
  const progressThumb = $('#progress-thumb');
  const timeCurrent  = $('#time-current');
  const timeTotal    = $('#time-total');
  const songTitle    = $('#song-title');
  const songSubtitle = $('#song-subtitle');
  const songSelect   = $('#song-select');

  // Background image elements
  const bgImage      = $('#bg-image');
  const bgImageNext  = $('#bg-image-next');
  const bgOverlay    = $('#bg-overlay');

  // ─── State ───
  let audio = null;
  let alignmentData = null;
  let lyricsLines = [];
  let lineElements = [];
  let activeLineIndex = -1;
  let isPlaying = false;
  let rafId = null;

  // Background image state
  let storyboard = [];
  let currentBgIndex = -1;
  let bgFlip = false;

  // ─── Helpers ───
  function fmtTime(sec) {
    if (!isFinite(sec) || sec < 0) sec = 0;
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  }

  // ─── Song List from Server ───
  async function loadSongList() {
    try {
      const resp = await fetch('/api/songs');
      const songs = await resp.json();

      songSelect.innerHTML = '';

      if (songs.length === 0) {
        songSelect.innerHTML = '<option value="">无歌曲 — 请运行 prepare.js</option>';
        return;
      }

      songSelect.innerHTML = '<option value="">选择歌曲…</option>';
      for (const s of songs) {
        if (!s.hasAudio || !s.hasAlignment) continue;
        const opt = document.createElement('option');
        opt.value = s.name;
        const imgs = s.imageCount ? ` · 🖼${s.imageCount}` : '';
        opt.textContent = `${s.name}${imgs}`;
        songSelect.appendChild(opt);
      }
    } catch (e) {
      songSelect.innerHTML = '<option value="">连接服务器失败</option>';
    }
  }

  songSelect.addEventListener('change', async () => {
    const name = songSelect.value;
    if (!name) return;
    await loadSong(name);
  });

  // ─── Load Song from Server ───
  async function loadSong(songName) {
    // Cleanup
    if (audio) {
      audio.pause();
      if (audio.src.startsWith('blob:')) URL.revokeObjectURL(audio.src);
    }
    if (rafId) cancelAnimationFrame(rafId);
    activeLineIndex = -1;

    songTitle.textContent = songName;
    songSubtitle.textContent = '加载中…';

    try {
      // Fetch alignment JSON
      const alignResp = await fetch(`/songs/${encodeURIComponent(songName)}/alignment.json`);
      alignmentData = await alignResp.json();

      // Create audio element
      audio = new Audio();
      audio.src = `/songs/${encodeURIComponent(songName)}/audio`;
      audio.preload = 'auto';

      // Get song metadata from API for image list
      const songsResp = await fetch('/api/songs');
      const songs = await songsResp.json();
      const songMeta = songs.find(s => s.name === songName);

      // Process lyrics
      processLyrics();

      // Process storyboard
      processStoryboard(alignmentData, songName, songMeta);

      const lineCount = alignmentData.lines.filter(l => l.text.trim() !== '...' && l.text.trim() !== '').length;
      songSubtitle.textContent = `${lineCount} 行歌词 · 逐字过光`;

      // Audio events
      audio.addEventListener('loadedmetadata', () => {
        timeTotal.textContent = fmtTime(audio.duration);
      });

      audio.addEventListener('ended', () => {
        isPlaying = false;
        updatePlayIcon();
      });

      // Start render loop
      startRenderLoop();
    } catch (e) {
      songSubtitle.textContent = `加载失败: ${e.message}`;
    }
  }

  // ─── Process Lyrics ───
  function processLyrics() {
    lyricsLines = [];
    lineElements = [];
    lyricsContainer.innerHTML = '';

    for (const line of alignmentData.lines) {
      const text = line.text.trim();
      const isInterlude = text === '...' || text === '' || text === '[Music]';

      const lineObj = {
        text, start: line.start, end: line.end,
        words: line.words || [],
        isInterlude,
        charTimings: []
      };

      if (!isInterlude) {
        let wordIdx = 0;
        for (let i = 0; i < text.length; i++) {
          const ch = text[i];
          if (ch === ' ' || ch === '\u3000') {
            lineObj.charTimings.push({ char: ch, start: null, end: null, isSpace: true });
          } else if (wordIdx < lineObj.words.length) {
            const w = lineObj.words[wordIdx];
            lineObj.charTimings.push({ char: ch, start: w.start, end: w.end, isSpace: false });
            wordIdx++;
          }
        }
      }

      lyricsLines.push(lineObj);

      const el = document.createElement('div');
      el.className = 'lyric-line';
      el.dataset.index = lyricsLines.length - 1;

      if (isInterlude) {
        el.classList.add('interlude');
        el.innerHTML = `<div class="interlude-dots"><span></span><span></span><span></span></div>`;
      } else {
        lineObj.charTimings.forEach((ct, ci) => {
          const span = document.createElement('span');
          span.className = 'char' + (ct.isSpace ? ' space' : '');
          span.textContent = ct.isSpace ? '' : ct.char;
          span.style.setProperty('--char-index', ci);
          el.appendChild(span);
        });
      }

      el.addEventListener('click', () => {
        if (!audio) return;
        const idx = parseInt(el.dataset.index);
        audio.currentTime = lyricsLines[idx].start;
        if (!isPlaying) {
          audio.play();
          isPlaying = true;
          updatePlayIcon();
        }
      });

      lyricsContainer.appendChild(el);
      lineElements.push(el);
    }
  }

  // ─── Render Loop ───
  function startRenderLoop() {
    if (rafId) cancelAnimationFrame(rafId);
    function tick() {
      if (audio) {
        const t = audio.currentTime;
        updateProgress(t);
        updateLyrics(t);
      }
      rafId = requestAnimationFrame(tick);
    }
    rafId = requestAnimationFrame(tick);
  }

  function updateProgress(t) {
    if (!audio || !audio.duration) return;
    const pct = (t / audio.duration) * 100;
    progressFill.style.width = pct + '%';
    progressGlow.style.width = pct + '%';
    progressThumb.style.left = pct + '%';
    timeCurrent.textContent = fmtTime(t);
    updateBackground(t);
  }

  // ─── Storyboard / Background Image Engine ───
  function processStoryboard(alignment, songName, songMeta) {
    storyboard = [];
    currentBgIndex = -1;
    bgFlip = false;
    bgImage.classList.remove('visible');
    bgImageNext.classList.remove('visible');
    bgImage.style.backgroundImage = '';
    bgImageNext.style.backgroundImage = '';

    if (!alignment.storyboard || !alignment.storyboard.length) {
      bgOverlay.classList.add('inactive');
      return;
    }

    // Build a set of available images from songMeta
    const availableImages = new Set(songMeta?.imageFiles || []);

    bgOverlay.classList.remove('inactive');

    for (const entry of alignment.storyboard) {
      const pathStr = entry.path || '';
      const parts = pathStr.split(/[/\\]/);
      const filename = parts[parts.length - 1];

      // Build URL if the image exists in the song's images folder
      const url = availableImages.has(filename)
        ? `/songs/${encodeURIComponent(songName)}/images/${encodeURIComponent(filename)}`
        : null;

      storyboard.push({
        start: entry.start,
        end: entry.end,
        filename,
        url
      });
    }
  }

  function updateBackground(currentTime) {
    if (!storyboard.length) return;

    let newIndex = -1;
    for (let i = 0; i < storyboard.length; i++) {
      if (currentTime >= storyboard[i].start && currentTime < storyboard[i].end) {
        newIndex = i;
        break;
      }
    }

    if (newIndex === currentBgIndex) return;
    currentBgIndex = newIndex;

    if (newIndex === -1 || !storyboard[newIndex].url) {
      bgImage.classList.remove('visible');
      bgImageNext.classList.remove('visible');
      return;
    }

    const url = storyboard[newIndex].url;

    if (bgFlip) {
      bgImageNext.style.backgroundImage = `url("${url}")`;
      bgImageNext.classList.add('visible');
      bgImage.classList.remove('visible');
    } else {
      bgImage.style.backgroundImage = `url("${url}")`;
      bgImage.classList.add('visible');
      bgImageNext.classList.remove('visible');
    }
    bgFlip = !bgFlip;
  }

  // ─── Lyrics Update ───
  function updateLyrics(currentTime) {
    let newActiveIndex = -1;
    for (let i = 0; i < lyricsLines.length; i++) {
      const ln = lyricsLines[i];
      if (currentTime >= ln.start && currentTime < ln.end) {
        newActiveIndex = i;
        break;
      }
    }

    if (newActiveIndex === -1) {
      for (let i = lyricsLines.length - 1; i >= 0; i--) {
        if (currentTime >= lyricsLines[i].end) {
          newActiveIndex = i;
          break;
        }
      }
    }

    if (newActiveIndex !== activeLineIndex) {
      activeLineIndex = newActiveIndex;
      updateLineClasses();
      scrollToActiveLine();
    }

    if (activeLineIndex >= 0 && !lyricsLines[activeLineIndex].isInterlude) {
      updateCharGlow(activeLineIndex, currentTime);
    }
  }

  function updateLineClasses() {
    lineElements.forEach((el, i) => {
      el.classList.remove('active', 'passed', 'upcoming');
      if (i === activeLineIndex) el.classList.add('active');
      else if (i < activeLineIndex) el.classList.add('passed');
      else if (i === activeLineIndex + 1) el.classList.add('upcoming');
    });
  }

  function scrollToActiveLine() {
    if (activeLineIndex < 0 || !lineElements[activeLineIndex]) return;
    const viewport = document.getElementById('lyrics-viewport');
    const activeEl = lineElements[activeLineIndex];
    const viewportHeight = viewport.clientHeight;
    const activeTop = activeEl.offsetTop;
    const activeHeight = activeEl.offsetHeight;
    const targetScroll = activeTop - (viewportHeight * 0.35) + (activeHeight / 2);
    lyricsContainer.style.transform = `translateY(${-targetScroll}px)`;
  }

  // ─── Character Gradient-Fill Engine ───
  function updateCharGlow(lineIndex, currentTime) {
    const line = lyricsLines[lineIndex];
    const el = lineElements[lineIndex];
    const chars = el.querySelectorAll('.char:not(.space)');
    const timings = line.charTimings.filter(ct => !ct.isSpace);

    let charIdx = 0;
    for (let i = 0; i < timings.length && charIdx < chars.length; i++) {
      const ct = timings[i];
      const span = chars[charIdx];
      charIdx++;

      if (!ct.start || !ct.end) continue;

      if (currentTime < ct.start) {
        span.style.setProperty('--fill', '0');
        span.classList.remove('singing');
      } else if (currentTime >= ct.start && currentTime < ct.end) {
        const progress = (currentTime - ct.start) / (ct.end - ct.start);
        const fillPct = Math.min(100, Math.max(0, progress * 100));
        span.style.setProperty('--fill', fillPct.toFixed(1));
        span.classList.add('singing');
      } else {
        span.style.setProperty('--fill', '100');
        span.classList.remove('singing');
      }
    }
  }

  // ─── Controls ───
  btnPlay.addEventListener('click', togglePlay);

  function togglePlay() {
    if (!audio) return;
    if (isPlaying) {
      audio.pause();
    } else {
      audio.play();
    }
    isPlaying = !isPlaying;
    updatePlayIcon();
  }

  function updatePlayIcon() {
    iconPlay.style.display = isPlaying ? 'none' : 'block';
    iconPause.style.display = isPlaying ? 'block' : 'none';
  }

  btnPrev.addEventListener('click', () => {
    if (!audio) return;
    const target = Math.max(0, activeLineIndex - 1);
    if (lyricsLines[target]) {
      audio.currentTime = lyricsLines[target].start;
      resetCharStates();
    }
  });

  btnNext.addEventListener('click', () => {
    if (!audio) return;
    const target = Math.min(lyricsLines.length - 1, activeLineIndex + 1);
    if (lyricsLines[target]) {
      audio.currentTime = lyricsLines[target].start;
      resetCharStates();
    }
  });

  // ─── Progress Bar Seeking ───
  progressBar.addEventListener('click', (e) => {
    if (!audio || !audio.duration) return;
    const rect = progressBar.getBoundingClientRect();
    const pct = (e.clientX - rect.left) / rect.width;
    audio.currentTime = pct * audio.duration;
    resetCharStates();
  });

  let isDragging = false;
  progressBar.addEventListener('mousedown', (e) => {
    isDragging = true;
    seekTo(e);
  });
  document.addEventListener('mousemove', (e) => { if (isDragging) seekTo(e); });
  document.addEventListener('mouseup', () => { isDragging = false; });

  function seekTo(e) {
    if (!audio || !audio.duration) return;
    const rect = progressBar.getBoundingClientRect();
    let pct = (e.clientX - rect.left) / rect.width;
    pct = Math.max(0, Math.min(1, pct));
    audio.currentTime = pct * audio.duration;
    resetCharStates();
  }

  function resetCharStates() {
    lineElements.forEach(el => {
      el.querySelectorAll('.char').forEach(span => {
        span.style.setProperty('--fill', '0');
        span.classList.remove('singing');
      });
    });
  }

  // ─── Keyboard Shortcuts ───
  document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;

    switch (e.code) {
      case 'Space':
        e.preventDefault();
        togglePlay();
        break;
      case 'ArrowUp':
        e.preventDefault();
        btnPrev.click();
        break;
      case 'ArrowDown':
        e.preventDefault();
        btnNext.click();
        break;
      case 'ArrowLeft':
        e.preventDefault();
        if (audio) { audio.currentTime = Math.max(0, audio.currentTime - 5); resetCharStates(); }
        break;
      case 'ArrowRight':
        e.preventDefault();
        if (audio) { audio.currentTime = Math.min(audio.duration, audio.currentTime + 5); resetCharStates(); }
        break;
    }
  });

  // ─── Init ───
  loadSongList();

})();
