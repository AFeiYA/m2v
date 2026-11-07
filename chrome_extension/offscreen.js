/**
 * Fovea MV - Offscreen WebCodecs Video Encoder
 *
 * Runs inside Chrome Manifest V3 Offscreen Document, enabling full access to:
 * - HTML5 Canvas & 2D Context rendering
 * - Web Audio API (AudioContext, decodeAudioData)
 * - WebCodecs VideoEncoder & AudioEncoder (GPU hardware acceleration)
 * - ArrayBufferTarget & mp4-muxer for MP4 packaging
 */

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.target !== 'offscreen') return;

  if (message.action === 'CHECK_WEBCODECS_SUPPORT') {
    const supported = typeof FoveaWebCodecs !== 'undefined' &&
      typeof FoveaWebCodecs.isWebCodecsSupported === 'function' &&
      FoveaWebCodecs.isWebCodecsSupported();
    sendResponse({ status: 'ok', supported });
    return false;
  }

  if (message.action === 'RENDER_WEBCODECS') {
    handleRenderWebCodecs(message)
      .then(result => sendResponse({ status: 'ok', data: result }))
      .catch(err => {
        console.error('[Offscreen] WebCodecs render error:', err);
        sendResponse({ status: 'error', message: err?.message || String(err) });
      });
    return true; // Keep message channel open for async response
  }
});

async function handleRenderWebCodecs(message) {
  const { project, audioUrl, audioHeaders, section, duration, aspect = '9:16', visualMode = 'kinetic', requestId, title } = message;

  if (typeof FoveaWebCodecs === 'undefined' || !FoveaWebCodecs.isWebCodecsSupported()) {
    throw new Error('WebCodecs is not supported in this browser environment');
  }

  if (!project) {
    throw new Error('Project alignment data is missing');
  }

  // 1. Normalize project
  const normalizedProject = FoveaWebCodecs.normalizeProject(project);

  // 2. Fetch audio if not pre-provided as ArrayBuffer
  let audioBlob;
  if (message.audioArrayBuffer) {
    audioBlob = new Blob([message.audioArrayBuffer], { type: 'audio/mpeg' });
  } else if (audioUrl) {
    const fetchOpts = {
      headers: audioHeaders || {},
      signal: AbortSignal.timeout(35000),
    };
    const resp = await fetch(audioUrl, fetchOpts);
    if (!resp.ok) throw new Error(`Audio download failed (HTTP ${resp.status})`);
    audioBlob = await resp.blob();
  } else {
    throw new Error('No audio source provided for video export');
  }

  // 3. Resolve clip range (start, length, title)
  const rangeInfo = FoveaWebCodecs.resolveClipRange(normalizedProject, section, duration);
  const range = {
    title: rangeInfo.title,
    aspect: aspect || '9:16',
    start: rangeInfo.start,
    length: rangeInfo.length,
    visualMode: visualMode || 'kinetic',
  };

  // 4. Progress callback
  let lastReportedPct = -1;
  const onProgress = ({ frame, totalFrames, pct }) => {
    const rounded = Math.round(pct);
    if (rounded !== lastReportedPct && (rounded % 5 === 0 || rounded >= 99 || frame === 1)) {
      lastReportedPct = rounded;
      chrome.runtime.sendMessage({
        action: 'WEBCODECS_PROGRESS',
        requestId,
        frame,
        totalFrames,
        pct: rounded,
      }).catch(() => {});
    }
  };

  // 5. Render using WebCodecs
  const videoBlob = await FoveaWebCodecs.exportMotionWebCodecs({
    project: normalizedProject,
    range,
    audioBlobOrUrl: audioBlob,
    onProgress,
  });

  // 6. Create Object URL for downloading
  const blobUrl = URL.createObjectURL(videoBlob);
  const suffix = { chorus: '_Chorus', verse1: '_Verse1', intro: '_Intro' }[section] || '';
  const safeTitle = (title || normalizedProject.title || 'lyric-video').replace(/[\\/:*?"<>|\x00-\x1f]/g, '_').slice(0, 110);
  const filename = `${safeTitle}${suffix}_9x16.mp4`;

  return {
    blobUrl,
    filename,
    size: videoBlob.size,
    duration: range.length,
  };
}
