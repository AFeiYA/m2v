#!/usr/bin/env node
/* ============================================================
   M2V Player — Lightweight Dev Server
   ============================================================
   Scans ./songs/ for song folders, serves API + static files.
   
   Directory convention:
     songs/
       匠心入梦01/
         audio.wav          (or .mp3/.ogg/.flac — any audio)
         alignment.json     (word-level timing data)
         images/            (optional background images)
           cover.png
           V (2).png
           ...

   API:
     GET /api/songs              → [{ name, hasAudio, hasAlignment, imageCount }]
     GET /songs/:name/audio      → redirects to the actual audio file
     GET /songs/:name/*          → static files in the song folder

   Usage:
     node server.js [port]       → default port 4567
   ============================================================ */

const http = require('http');
const fs = require('fs');
const path = require('path');
const url = require('url');

const PORT = parseInt(process.argv[2]) || 4567;
const PLAYER_DIR = __dirname;
const SONGS_DIR = path.join(PLAYER_DIR, 'songs');

// ─── MIME types ───
const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css':  'text/css; charset=utf-8',
  '.js':   'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png':  'image/png',
  '.jpg':  'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.gif':  'image/gif',
  '.svg':  'image/svg+xml',
  '.wav':  'audio/wav',
  '.mp3':  'audio/mpeg',
  '.ogg':  'audio/ogg',
  '.flac': 'audio/flac',
  '.m4a':  'audio/mp4',
  '.woff2': 'font/woff2',
  '.woff':  'font/woff',
};

const AUDIO_EXTS = ['.wav', '.mp3', '.ogg', '.flac', '.m4a'];

// ─── Helpers ───
function getMime(filePath) {
  return MIME[path.extname(filePath).toLowerCase()] || 'application/octet-stream';
}

function serveFile(res, filePath) {
  if (!fs.existsSync(filePath)) {
    res.writeHead(404);
    res.end('Not found');
    return;
  }
  const stat = fs.statSync(filePath);
  res.writeHead(200, {
    'Content-Type': getMime(filePath),
    'Content-Length': stat.size,
    'Cache-Control': 'no-cache',
  });
  fs.createReadStream(filePath).pipe(res);
}

function serveJSON(res, data) {
  const body = JSON.stringify(data);
  res.writeHead(200, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(body),
    'Cache-Control': 'no-cache',
  });
  res.end(body);
}

/** Find the first audio file in a directory */
function findAudio(dir) {
  if (!fs.existsSync(dir)) return null;
  const files = fs.readdirSync(dir);
  for (const f of files) {
    if (AUDIO_EXTS.includes(path.extname(f).toLowerCase())) {
      return f;
    }
  }
  return null;
}

/** Scan songs directory */
function scanSongs() {
  if (!fs.existsSync(SONGS_DIR)) {
    fs.mkdirSync(SONGS_DIR, { recursive: true });
    return [];
  }
  const entries = fs.readdirSync(SONGS_DIR, { withFileTypes: true });
  const songs = [];
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const songDir = path.join(SONGS_DIR, entry.name);
    const audioFile = findAudio(songDir);
    const hasAlignment = fs.existsSync(path.join(songDir, 'alignment.json'));
    const hasAnalysis = fs.existsSync(path.join(songDir, 'analysis.json'));
    const imagesDir = path.join(songDir, 'images');
    let imageCount = 0;
    let imageFiles = [];
    if (fs.existsSync(imagesDir)) {
      imageFiles = fs.readdirSync(imagesDir).filter(f =>
        /\.(png|jpg|jpeg|webp|gif)$/i.test(f)
      );
      imageCount = imageFiles.length;
    }
    songs.push({
      name: entry.name,
      hasAudio: !!audioFile,
      audioFile: audioFile,
      hasAlignment: hasAlignment,
      hasAnalysis: hasAnalysis,
      imageCount: imageCount,
      imageFiles: imageFiles,
    });
  }
  return songs;
}

// ─── Server ───
const server = http.createServer((req, res) => {
  // CORS
  res.setHeader('Access-Control-Allow-Origin', '*');

  const parsed = url.parse(req.url, true);
  let pathname = decodeURIComponent(parsed.pathname);

  // API: song list
  if (pathname === '/api/songs') {
    return serveJSON(res, scanSongs());
  }

  // Songs static files: /songs/{name}/audio → find & serve audio file
  if (pathname.startsWith('/songs/')) {
    const rest = pathname.slice('/songs/'.length);
    const slashIdx = rest.indexOf('/');
    if (slashIdx === -1) {
      res.writeHead(400);
      return res.end('Bad request');
    }
    const songName = rest.slice(0, slashIdx);
    let filePart = rest.slice(slashIdx + 1);

    const songDir = path.join(SONGS_DIR, songName);

    // Special route: /songs/{name}/audio → find audio file
    if (filePart === 'audio') {
      const audioFile = findAudio(songDir);
      if (!audioFile) {
        res.writeHead(404);
        return res.end('No audio file found');
      }
      return serveFile(res, path.join(songDir, audioFile));
    }

    // Otherwise serve the file directly
    const filePath = path.join(songDir, filePart);
    // Security: ensure we stay within songs directory
    if (!filePath.startsWith(SONGS_DIR)) {
      res.writeHead(403);
      return res.end('Forbidden');
    }
    return serveFile(res, filePath);
  }

  // Static player files
  if (pathname === '/' || pathname === '') pathname = '/index.html';
  
  // Don't serve server.js or songs directory listing
  if (pathname === '/server.js' || pathname === '/prepare.js') {
    res.writeHead(403);
    return res.end('Forbidden');
  }

  const filePath = path.join(PLAYER_DIR, pathname);
  if (!filePath.startsWith(PLAYER_DIR)) {
    res.writeHead(403);
    return res.end('Forbidden');
  }
  serveFile(res, filePath);
});

server.listen(PORT, () => {
  console.log(`\n  🎤 M2V Player Server`);
  console.log(`  ────────────────────`);
  console.log(`  http://localhost:${PORT}\n`);
  
  const songs = scanSongs();
  if (songs.length === 0) {
    console.log(`  ⚠  songs/ 目录为空，请运行 prepare.js 或手动放置文件`);
    console.log(`  📁 目录结构:`);
    console.log(`     songs/`);
    console.log(`       歌名/`);
    console.log(`         audio.wav (.mp3/.flac)`);
    console.log(`         alignment.json`);
    console.log(`         images/`);
    console.log(`           cover.png\n`);
  } else {
    console.log(`  🎵 已发现 ${songs.length} 首歌曲:`);
    for (const s of songs) {
      const status = [];
      if (s.hasAudio) status.push('🔊 音频');
      else status.push('⚠ 缺音频');
      if (s.hasAlignment) status.push('📋 对齐');
      else status.push('⚠ 缺对齐');
      if (s.imageCount) status.push(`🖼 ${s.imageCount}张图`);
      console.log(`     ${s.name}  [${status.join(' | ')}]`);
    }
    console.log('');
  }
});
