/**
 * Suno2MV — Motion Studio (动效与音乐节奏工坊)
 * ============================================================================
 * 纯确定性音乐动效控制器：波形驱动、逐字高亮、卡点微调、预设切换与实时渲染
 * ============================================================================
 */

(function () {
  'use strict';

  // 状态树
  const state = {
    currentFile: null,
    alignment: null,
    dsl: null,
    bpm: 120.0,
    beats: [],
    drumHits: [],
    cues: [],
    selectedCue: null,
    isLoopingCue: false,
    aspectRatio: '16:9',
  };

  // DOM 元素缓存
  const dom = {
    selectFile: document.getElementById('select-file'),
    badgeBpm: document.getElementById('badge-bpm'),
    viewportBox: document.getElementById('viewport-box'),
    hudTime: document.getElementById('hud-time'),
    hudBeat: document.getElementById('hud-beat'),
    hudPhrase: document.getElementById('hud-phrase'),
    hudPhraseBox: document.getElementById('hud-phrase-box'),
    btnToggleRatio: document.getElementById('btn-toggle-ratio'),
    btnToggleGrid: document.getElementById('btn-toggle-grid'),
    activeLyricBar: document.getElementById('active-lyric-bar'),
    btnPlay: document.getElementById('btn-play'),
    timeCurrent: document.getElementById('time-current'),
    timeTotal: document.getElementById('time-total'),
    chkLoopCue: document.getElementById('chk-loop-cue'),
    sliderZoom: document.getElementById('slider-zoom'),
    cueBlocksTrack: document.getElementById('cue-blocks-track'),
    selectPreset: document.getElementById('select-preset'),
    sliderRecoil: document.getElementById('slider-recoil'),
    valRecoil: document.getElementById('val-recoil'),
    sliderSlam: document.getElementById('slider-slam'),
    valSlam: document.getElementById('val-slam'),
    sliderSplit: document.getElementById('slider-split'),
    valSplit: document.getElementById('val-split'),
    cuesListContainer: document.getElementById('cues-list-container'),
    inputBpm: document.getElementById('input-bpm'),
    valBeatsCount: document.getElementById('val-beats-count'),
    valDrumsCount: document.getElementById('val-drums-count'),
    btnExportDsl: document.getElementById('btn-export-dsl'),
    tabs: document.querySelectorAll('.tab-btn'),
  };

  let ws = null;
  let kineticRuntime = null;

  // ---------------------------------------------------------------------------
  // 1. 初始化入口
  // ---------------------------------------------------------------------------
  document.addEventListener('DOMContentLoaded', () => {
    initWaveSurfer();
    initKineticRuntime();
    bindEvents();
    loadFileList();
  });

  function initWaveSurfer() {
    if (typeof WaveSurfer === 'undefined') {
      console.error('WaveSurfer 未加载');
      return;
    }

    ws = WaveSurfer.create({
      container: '#waveform',
      waveColor: '#1e293b',
      progressColor: '#00f0ff',
      cursorColor: '#ff007f',
      cursorWidth: 2,
      height: 58,
      normalize: true,
      minPxPerSec: 80,
      fillParent: true,
      hideScrollbar: false,
    });

    ws.on('play', () => {
      if (dom.btnPlay) dom.btnPlay.textContent = '⏸';
    });

    ws.on('pause', () => {
      if (dom.btnPlay) dom.btnPlay.textContent = '▶';
    });

    ws.on('ready', () => {
      const dur = ws.getDuration();
      if (dom.timeTotal) dom.timeTotal.textContent = formatTime(dur);
    });

    ws.on('audioprocess', () => {
      const t = ws.getCurrentTime();
      onTick(t);
    });

    ws.on('seek', () => {
      const t = ws.getCurrentTime();
      onTick(t);
    });
  }

  function initKineticRuntime() {
    if (typeof DeterministicMotionRuntime === 'undefined') {
      console.error('DeterministicMotionRuntime 未加载');
      return;
    }

    kineticRuntime = new DeterministicMotionRuntime({
      container: '#kinetic-motion-stage',
      preset: dom.selectPreset ? dom.selectPreset.value : 'pdoom_cyber',
      enabled: true,
    });
    window.kineticRuntime = kineticRuntime;
  }

  // ---------------------------------------------------------------------------
  // 2. 音频时钟主循环 (Master Tick)
  // ---------------------------------------------------------------------------
  function onTick(t) {
    // 1. 更新 HUD 时钟
    if (dom.hudTime) dom.hudTime.textContent = `${t.toFixed(3)}s`;
    if (dom.timeCurrent) dom.timeCurrent.textContent = formatTime(t);

    // 2. 更新拍号 HUD
    const bpm = state.bpm || 120.0;
    const beatIndex = Math.floor((t * bpm) / 60) + 1;
    const totalBeats = state.beats.length || Math.floor(((state.alignment?.duration || 180) * bpm) / 60);
    if (dom.hudBeat) dom.hudBeat.textContent = `${beatIndex} / ${totalBeats}`;

    // 3. 驱动确定性运动引擎纯函数寻址
    if (kineticRuntime) {
      kineticRuntime.renderAt(t);
    }

    // 4. 寻址当前活跃的歌词词组与音节
    updateActiveLyricDisplay(t);

    // 5. 循环当前词组逻辑 (精调单句模式)
    if (state.isLoopingCue && state.selectedCue) {
      if (t >= state.selectedCue.end) {
        ws.seekTo(Math.max(0, state.selectedCue.start) / ws.getDuration());
      }
    }
  }

  function updateActiveLyricDisplay(t) {
    if (!state.cues || state.cues.length === 0) return;

    let activeCue = null;
    for (let i = 0; i < state.cues.length; i++) {
      const cue = state.cues[i];
      if (t >= cue.start && t <= cue.end) {
        activeCue = cue;
        break;
      }
    }

    if (activeCue) {
      if (dom.hudPhrase && dom.hudPhraseBox) {
        dom.hudPhrase.textContent = activeCue.text;
        dom.hudPhraseBox.style.display = 'inline-flex';
      }

      // 高亮词组轨中的对应块
      highlightCueBlock(activeCue.cue_id);

      // 发音大字提词器逐音节高亮
      if (dom.activeLyricBar) {
        const words = activeCue.words || [];
        if (words.length > 0) {
          let html = '';
          for (let i = 0; i < words.length; i++) {
            const w = words[i];
            const isSinging = t >= Number(w.start) && t <= Number(w.end);
            if (isSinging) {
              html += `<span class="highlight-word">${escapeHtml(w.word)}</span>`;
            } else {
              html += `<span>${escapeHtml(w.word)}</span>`;
            }
          }
          dom.activeLyricBar.innerHTML = html;
        } else {
          dom.activeLyricBar.textContent = activeCue.text;
        }
      }
    } else {
      if (dom.hudPhraseBox) dom.hudPhraseBox.style.display = 'none';
      unhighlightCueBlocks();
    }
  }

  // ---------------------------------------------------------------------------
  // 3. 项目加载与 DSL 转换
  // ---------------------------------------------------------------------------
  const filesMap = new Map();

  async function loadFileList() {
    try {
      const res = await fetch('/api/files');
      if (!res.ok) throw new Error('获取文件列表失败');
      const files = await res.json();

      if (!dom.selectFile) return;
      dom.selectFile.innerHTML = '';
      filesMap.clear();

      if (files.length === 0) {
        dom.selectFile.innerHTML = '<option value="">无项目</option>';
        return;
      }

      files.forEach((f) => {
        filesMap.set(f.json_path, f);
        const opt = document.createElement('option');
        opt.value = f.json_path;
        opt.textContent = f.name;
        dom.selectFile.appendChild(opt);
      });

      // 优先选中 04tuZiDongV1 或 URL 中的指定歌曲
      const urlParams = new URLSearchParams(window.location.search);
      const targetSong = urlParams.get('song') || '04tuZiDongV1';
      const targetOpt = Array.from(dom.selectFile.options).find(
        (o) => o.text.includes(targetSong) || o.value.includes(targetSong)
      );

      if (targetOpt) {
        dom.selectFile.value = targetOpt.value;
      }

      loadProject(dom.selectFile.value);
    } catch (err) {
      console.error('[MotionStudio] 加载文件列表异常:', err);
    }
  }

  async function loadProject(jsonPath) {
    if (!jsonPath) return;
    try {
      const res = await fetch(`/api/alignment?path=${encodeURIComponent(jsonPath)}`);
      if (!res.ok) throw new Error(`加载项目失败: ${res.statusText}`);
      const project = await res.json();
      state.alignment = project;
      state.currentFile = { path: jsonPath, name: jsonPath.split('/').pop().replace('_alignment.json', '') };

      // 提取音乐特征
      const analysis = project.analysis || {};
      state.bpm = Number(analysis.bpm || 120.0);
      state.beats = Array.isArray(analysis.beats) ? analysis.beats.map(Number) : [];
      state.drumHits = Array.isArray(analysis.drum_hits) ? analysis.drum_hits : [];

      if (dom.badgeBpm) {
        dom.badgeBpm.textContent = `⚡ ${state.bpm.toFixed(1)} BPM`;
        dom.badgeBpm.style.display = 'inline-flex';
      }
      if (dom.inputBpm) dom.inputBpm.value = state.bpm.toFixed(1);
      if (dom.valBeatsCount) dom.valBeatsCount.textContent = String(state.beats.length);
      if (dom.valDrumsCount) dom.valDrumsCount.textContent = String(state.drumHits.length);

      // 构建 Motion Timeline DSL
      buildMotionDSL();

      // 加载音频 (优先使用 /api/files 索引到的物理路径)
      const fileMeta = filesMap.get(jsonPath) || {};
      const audioPath = fileMeta.audio_path || (fileMeta.audio_tracks && fileMeta.audio_tracks.vocals) || project.audio_path || '';
      if (audioPath && ws) {
        const audioUrl = `/api/audio?path=${encodeURIComponent(audioPath)}`;
        ws.load(audioUrl);
      }

      // 渲染底部时间轨与右侧列表
      renderCueBlocksTrack();
      renderCuesList();
    } catch (err) {
      console.error('[MotionStudio] 加载工程数据失败:', err);
    }
  }

  function buildMotionDSL() {
    if (!state.alignment) return;
    let shots = state.alignment.storyboard || [];
    const lines = state.alignment.lines || [];

    // 若无分镜镜头，自动从歌词行派生动效场景
    if (shots.length === 0 && lines.length > 0) {
      shots = lines.map((l, i) => ({
        id: `shot_${String(i + 1).padStart(3, '0')}`,
        shot_id: i + 1,
        start: Number(l.start),
        end: Number(l.end),
        semantic_groups: (l.style_overrides && l.style_overrides.semantic_groups) || [],
      }));
    }

    const allCues = [];
    const scenes = shots.map((s, idx) => {
      const shotId = s.id || `shot_${String(s.shot_id || idx + 1).padStart(3, '0')}`;
      const start = Number(s.start) || 0;
      const end = Number(s.end) || 0;

      const matchedLines = lines.filter(
        (l) => (l.start >= start - 0.2 && l.start < end) || (l.end > start && l.end <= end + 0.2)
      );
      const cues = [];

      // 优先从镜头或行的 style_overrides 获取自然语义组
      let semGroups = s.semantic_groups || [];
      if (semGroups.length === 0) {
        matchedLines.forEach((l) => {
          if (l.style_overrides && Array.isArray(l.style_overrides.semantic_groups)) {
            semGroups = semGroups.concat(l.style_overrides.semantic_groups);
          }
        });
      }

      if (semGroups.length > 0) {
        semGroups.forEach((g, gIdx) => {
          const text = g.phrase || g.text || '';
          if (!text) return;
          const gStart = Number(g.start !== undefined ? g.start : start);
          const gEnd = Number(g.end !== undefined ? g.end : end);
          const emp = Number(g.emphasis !== undefined ? g.emphasis : gIdx === 0 ? 0.85 : 0.7);

          const phraseWords = [];
          matchedLines.forEach((l) => {
            (l.words || []).forEach((w) => {
              if (w.start >= gStart - 0.08 && w.end <= gEnd + 0.08) {
                phraseWords.push({
                  word: w.word,
                  start: Number(w.start),
                  end: Number(w.end),
                });
              }
            });
          });

          const cue = {
            cue_id: `${shotId}:phrase_${String(gIdx + 1).padStart(2, '0')}`,
            text: text,
            start: gStart,
            end: gEnd,
            emphasis: emp,
            words: phraseWords,
            role: emp >= 0.8 ? 'hero' : 'connector',
          };
          cues.push(cue);
          allCues.push(cue);
        });
      } else {
        // 降级: 自然语义切词
        let count = 0;
        matchedLines.forEach((l) => {
          const words = l.words || [];
          if (words.length > 0) {
            const chunks = [];
            let cur = [words[0]];
            for (let i = 1; i < words.length; i++) {
              const prev = words[i - 1];
              const curr = words[i];
              const gap = curr.start - prev.end;
              if (gap > 0.22 || [' ', '，', '、', '！', '？', ',', '!'].includes(prev.word) || cur.length >= 5) {
                chunks.push(cur);
                cur = [curr];
              } else {
                cur.push(curr);
              }
            }
            if (cur.length > 0) chunks.push(cur);

            chunks.forEach((chunk) => {
              const chunkText = chunk.map((w) => w.word).join('').replace(/[ ，、！？,!]/g, '');
              if (!chunkText) return;
              count++;
              const emp = count === 1 ? 0.85 : 0.65;
              const cue = {
                cue_id: `${shotId}:chunk_${String(count).padStart(2, '0')}`,
                text: chunkText,
                start: Number(chunk[0].start),
                end: Number(chunk[chunk.length - 1].end),
                emphasis: emp,
                words: chunk.map((w) => ({ word: w.word, start: Number(w.start), end: Number(w.end) })),
                role: emp >= 0.8 ? 'hero' : 'stagger',
              };
              cues.push(cue);
              allCues.push(cue);
            });
          } else if (l.text) {
            count++;
            const cue = {
              cue_id: `${shotId}:line_${String(count).padStart(2, '0')}`,
              text: l.text,
              start: Number(l.start),
              end: Number(l.end),
              emphasis: 0.8,
              role: 'hero',
            };
            cues.push(cue);
            allCues.push(cue);
          }
        });
      }

      return {
        scene_id: shotId,
        start: start,
        end: end,
        layers: [
          {
            type: 'kinetic_typography',
            preset: kineticRuntime ? kineticRuntime.preset : 'pdoom_cyber',
            seed: `${shotId}:kinetic_seed`,
            cues: cues,
          },
        ],
      };
    });

    state.cues = allCues;
    state.dsl = {
      version: '1.0.0',
      meta: {
        title: state.currentFile?.name || 'MV Project',
        bpm: state.bpm,
        beats: state.beats,
        drum_hits: state.drumHits,
      },
      scenes: scenes,
    };

    if (kineticRuntime) {
      kineticRuntime.setAudioFeatures({
        bpm: state.bpm,
        beats: state.beats,
        drum_hits: state.drumHits,
      });
      kineticRuntime.setTimeline(state.dsl);
    }
  }

  // ---------------------------------------------------------------------------
  // 4. 界面渲染 (Cue Blocks & Inspector List)
  // ---------------------------------------------------------------------------
  function renderCueBlocksTrack() {
    if (!dom.cueBlocksTrack) return;
    dom.cueBlocksTrack.innerHTML = '';

    state.cues.forEach((c) => {
      const el = document.createElement('div');
      el.className = `cue-block ${c.role === 'hero' ? 'is-hero' : ''}`;
      el.id = `cue-block-${c.cue_id}`;
      el.textContent = c.text;
      el.title = `${c.text} (${c.start.toFixed(2)}s ~ ${c.end.toFixed(2)}s) [${c.role.toUpperCase()}]`;

      el.addEventListener('click', () => {
        selectCue(c);
        if (ws) {
          const dur = ws.getDuration();
          if (dur > 0) ws.seekTo(Math.max(0, c.start) / dur);
        }
      });

      dom.cueBlocksTrack.appendChild(el);
    });
  }

  function renderCuesList() {
    if (!dom.cuesListContainer) return;
    dom.cuesListContainer.innerHTML = '';

    state.cues.forEach((c) => {
      const item = document.createElement('div');
      item.className = 'cue-list-item';
      item.id = `cue-item-${c.cue_id}`;
      item.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="font-weight: 700; color: #fff;">${escapeHtml(c.text)}</span>
          <span style="font-size: 10px; padding: 1px 6px; border-radius: 3px; background: ${c.role === 'hero' ? 'rgba(0,240,255,0.2)' : 'rgba(255,255,255,0.1)'}; color: ${c.role === 'hero' ? '#00f0ff' : '#94a3b8'};">
            ${c.role.toUpperCase()}
          </span>
        </div>
        <div style="font-size: 11px; color: #64748b; font-family: monospace;">
          ${c.start.toFixed(2)}s ~ ${c.end.toFixed(2)}s (${(c.end - c.start).toFixed(2)}s)
        </div>
      `;

      item.addEventListener('click', () => {
        selectCue(c);
        if (ws) {
          const dur = ws.getDuration();
          if (dur > 0) ws.seekTo(Math.max(0, c.start) / dur);
        }
      });

      dom.cuesListContainer.appendChild(item);
    });
  }

  function selectCue(cue) {
    state.selectedCue = cue;
    document.querySelectorAll('.cue-list-item').forEach((i) => i.classList.remove('selected'));
    const item = document.getElementById(`cue-item-${cue.cue_id}`);
    if (item) item.classList.add('selected');
    highlightCueBlock(cue.cue_id);
  }

  function highlightCueBlock(cueId) {
    document.querySelectorAll('.cue-block').forEach((b) => b.classList.remove('active'));
    const b = document.getElementById(`cue-block-${cueId}`);
    if (b) {
      b.classList.add('active');
      b.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
    }
  }

  function unhighlightCueBlocks() {
    document.querySelectorAll('.cue-block').forEach((b) => b.classList.remove('active'));
  }

  // ---------------------------------------------------------------------------
  // 5. 事件绑定
  // ---------------------------------------------------------------------------
  function bindEvents() {
    // 播放/暂停
    if (dom.btnPlay) {
      dom.btnPlay.addEventListener('click', () => {
        if (ws) ws.playPause();
      });
    }

    // 键盘空格键播放/暂停
    window.addEventListener('keydown', (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
      if (e.code === 'Space') {
        e.preventDefault();
        if (ws) ws.playPause();
      }
    });

    // 切换文件
    if (dom.selectFile) {
      dom.selectFile.addEventListener('change', (e) => {
        loadProject(e.target.value);
      });
    }

    // 预设切换
    if (dom.selectPreset) {
      dom.selectPreset.addEventListener('change', (e) => {
        if (kineticRuntime) {
          kineticRuntime.setPreset(e.target.value);
          if (ws) kineticRuntime.renderAt(ws.getCurrentTime());
        }
      });
    }

    // 切换 16:9 与 9:16
    if (dom.btnToggleRatio) {
      dom.btnToggleRatio.addEventListener('click', () => {
        state.aspectRatio = state.aspectRatio === '16:9' ? '9:16' : '16:9';
        dom.btnToggleRatio.textContent = state.aspectRatio === '16:9' ? '📱 16:9' : '📲 9:16';
        if (dom.viewportBox) {
          dom.viewportBox.classList.toggle('portrait-mode', state.aspectRatio === '9:16');
        }
      });
    }

    // 循环单句复选框
    if (dom.chkLoopCue) {
      dom.chkLoopCue.addEventListener('change', (e) => {
        state.isLoopingCue = e.target.checked;
      });
    }

    // 波形缩放
    if (dom.sliderZoom) {
      dom.sliderZoom.addEventListener('input', (e) => {
        if (ws) ws.zoom(Number(e.target.value));
      });
    }

    // 物理参数滑块
    if (dom.sliderRecoil && dom.valRecoil) {
      dom.sliderRecoil.addEventListener('input', (e) => {
        dom.valRecoil.textContent = `${Number(e.target.value).toFixed(1)}x`;
      });
    }
    if (dom.sliderSlam && dom.valSlam) {
      dom.sliderSlam.addEventListener('input', (e) => {
        dom.valSlam.textContent = `${Number(e.target.value).toFixed(1)}x`;
      });
    }
    if (dom.sliderSplit && dom.valSplit) {
      dom.sliderSplit.addEventListener('input', (e) => {
        dom.valSplit.textContent = `${Number(e.target.value)}px`;
      });
    }

    // 导出 DSL JSON
    if (dom.btnExportDsl) {
      dom.btnExportDsl.addEventListener('click', () => {
        if (!state.dsl) return;
        const jsonStr = JSON.stringify(state.dsl, null, 2);
        const blob = new Blob([jsonStr], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${state.currentFile?.name || 'motion'}_dsl.json`;
        a.click();
        URL.revokeObjectURL(url);
      });
    }

    // 控制台 Tab 切换
    dom.tabs.forEach((tab) => {
      tab.addEventListener('click', () => {
        dom.tabs.forEach((t) => t.classList.remove('active'));
        tab.classList.add('active');
        const target = tab.dataset.tab;
        document.getElementById('tab-content-physics').style.display = target === 'physics' ? 'flex' : 'none';
        document.getElementById('tab-content-cues').style.display = target === 'cues' ? 'flex' : 'none';
        document.getElementById('tab-content-audio').style.display = target === 'audio' ? 'flex' : 'none';
      });
    });
  }

  // ---------------------------------------------------------------------------
  // 工具函数
  // ---------------------------------------------------------------------------
  function formatTime(sec) {
    const s = Math.max(0, Number(sec) || 0);
    const mins = Math.floor(s / 60);
    const rem = s % 60;
    return `${String(mins).padStart(2, '0')}:${rem.toFixed(2).padStart(5, '0')}`;
  }

  function escapeHtml(str) {
    return String(str || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }
})();
