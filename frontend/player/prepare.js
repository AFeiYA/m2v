#!/usr/bin/env node
/* ============================================================
   M2V Player — Prepare Songs Directory
   ============================================================
   Scans the M2V project output/ and input/ directories,
   copies (or symlinks) files into the player's songs/ folder.
   
   Usage:
     node prepare.js
   ============================================================ */

const fs = require('fs');
const path = require('path');

// Paths — relative to this script's location
const SCRIPT_DIR = __dirname;
const PROJECT_ROOT = path.resolve(SCRIPT_DIR, '..', '..');
const INPUT_DIR = path.join(PROJECT_ROOT, 'input');
const OUTPUT_DIR = path.join(PROJECT_ROOT, 'output');
const ASSETS_DIR = path.join(PROJECT_ROOT, 'assets');
const SONGS_DIR = path.join(SCRIPT_DIR, 'songs');

const AUDIO_EXTS = ['.wav', '.mp3', '.ogg', '.flac', '.m4a'];

function ensureDir(dir) {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

function copyFile(src, dest) {
  if (fs.existsSync(src)) {
    fs.copyFileSync(src, dest);
    return true;
  }
  return false;
}

function main() {
  console.log('\n  🔧 M2V Player — 准备歌曲目录\n');

  // Find alignment files in output/
  if (!fs.existsSync(OUTPUT_DIR)) {
    console.log('  ⚠ output/ 目录不存在');
    return;
  }

  const outputFiles = fs.readdirSync(OUTPUT_DIR);
  const alignmentFiles = outputFiles.filter(f => f.endsWith('_alignment.json'));

  if (alignmentFiles.length === 0) {
    console.log('  ⚠ 没有找到 *_alignment.json 文件');
    return;
  }

  console.log(`  📋 发现 ${alignmentFiles.length} 个对齐文件\n`);

  for (const alignFile of alignmentFiles) {
    // Extract song name: "匠心入梦01_alignment.json" → "匠心入梦01"
    const songName = alignFile.replace('_alignment.json', '');
    const songDir = path.join(SONGS_DIR, songName);
    const imagesDir = path.join(songDir, 'images');

    ensureDir(songDir);
    ensureDir(imagesDir);

    console.log(`  🎵 ${songName}`);

    // 1. Copy alignment.json
    const alignSrc = path.join(OUTPUT_DIR, alignFile);
    const alignDest = path.join(songDir, 'alignment.json');
    if (copyFile(alignSrc, alignDest)) {
      console.log(`     ✓ alignment.json`);
    } else if (fs.existsSync(alignDest)) {
      console.log(`     · alignment.json (已存在)`);
    }

    // 1b. Copy analysis.json
    const analysisSrc = path.join(OUTPUT_DIR, songName + '_analysis.json');
    const analysisDest = path.join(songDir, 'analysis.json');
    if (copyFile(analysisSrc, analysisDest)) {
      console.log(`     ✓ analysis.json`);
    } else if (fs.existsSync(analysisDest)) {
      console.log(`     · analysis.json (已存在)`);
    }

    // 2. Find and copy audio file from input/
    let audioFound = false;
    for (const ext of AUDIO_EXTS) {
      const audioSrc = path.join(INPUT_DIR, songName + ext);
      if (fs.existsSync(audioSrc)) {
        const audioDest = path.join(songDir, 'audio' + ext);
        if (copyFile(audioSrc, audioDest)) {
          console.log(`     ✓ audio${ext}`);
        } else if (fs.existsSync(audioDest)) {
          console.log(`     · audio${ext} (已存在)`);
        }
        audioFound = true;
        break;
      }
    }
    if (!audioFound) {
      console.log(`     ⚠ 未找到音频文件 (input/${songName}.*)`);
    }

    // 3. Parse alignment.json for storyboard images
    try {
      const alignData = JSON.parse(fs.readFileSync(alignSrc, 'utf8'));
      if (alignData.storyboard && alignData.storyboard.length) {
        let imgCopied = 0;
        const seenFiles = new Set();
        for (const entry of alignData.storyboard) {
          if (!entry.path) continue;
          // Extract filename from path
          const parts = entry.path.split(/[/\\]/);
          const filename = parts[parts.length - 1];
          if (seenFiles.has(filename)) continue;
          seenFiles.add(filename);

          // Try to find the image file
          const candidates = [
            entry.path, // Original absolute path
            path.join(ASSETS_DIR, filename), // assets/ directory
          ];
          for (const candidate of candidates) {
            if (fs.existsSync(candidate)) {
              const imgDest = path.join(imagesDir, filename);
              if (copyFile(candidate, imgDest)) {
                imgCopied++;
              }
              break;
            }
          }
        }
        if (imgCopied > 0) {
          console.log(`     ✓ ${imgCopied} 张背景图片`);
        }
        const existingImgs = fs.readdirSync(imagesDir).filter(f =>
          /\.(png|jpg|jpeg|webp|gif)$/i.test(f)
        );
        if (existingImgs.length > 0 && imgCopied === 0) {
          console.log(`     · ${existingImgs.length} 张图片 (已存在)`);
        }
      }
    } catch (e) {
      console.log(`     ⚠ 解析 alignment.json 失败: ${e.message}`);
    }

    console.log('');
  }

  console.log(`  ✅ 完成！运行 node server.js 启动播放器\n`);
}

main();
