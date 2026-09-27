/* ============================================================
   M2V 3D Ride Game Engine — Three.js + Web Audio API
   ============================================================ */

(() => {
  'use strict';

  // ─── DOM References ───
  const container = document.getElementById('game-canvas-container');
  const hudScore = document.getElementById('hud-score');
  const hudCombo = document.getElementById('hud-combo');
  const shieldFill = document.getElementById('shield-fill');
  const hudSpeed = document.getElementById('hud-speed');
  const songTitle = document.getElementById('game-song-title');
  const songBpm = document.getElementById('game-song-bpm');
  const currentLyric = document.getElementById('game-current-lyric');
  const nextLyricText = document.getElementById('game-next-lyric');
  const startOverlay = document.getElementById('start-overlay');
  const resultsOverlay = document.getElementById('results-overlay');
  const judgmentDisplay = document.getElementById('judgment-display');
  const screenFlash = document.getElementById('screen-flash');
  const btnStart = document.getElementById('btn-start-game');
  const btnRestart = document.getElementById('btn-restart');
  const btnBackMenu = document.getElementById('btn-back-menu');
  const songSelect = document.getElementById('game-song-select');
  const bgAudio = document.getElementById('bg-audio');
  const gameBgLayer = document.getElementById('game-bg-layer');

  // ─── Game Tuning Constants ───
  const BASE_SPEED = 40.0;     // Units traveled per second along Z axis
  const LANE_SPACING = 2.2;    // Space between lanes (0=Left, 1=Center, 2=Right)
  const LOOK_AHEAD_TIME = 0.15;// Look-ahead for ship orientation (seconds)
  const SHIELD_MAX = 100;

  // ─── Three.js Globals ───
  let scene, camera, renderer;
  let trackCurve = null;
  let laneCurves = [];
  let laneLines = [];
  let shipGroup = null;
  let shipTargetX = 0.0;       // Smooth target X for steering
  let shipCurrentX = 0.0;
  let shipRoll = 0.0;
  let starField = null;
  let visualizerPillars = [];
  
  // ─── Gameplay Entities ───
  let activeGameObjects = [];  // Floating gems, spikes, cymbals
  let activeLyricSpans = [];   // HTML spans for highlighting
  let lineTimings = [];        // Lyric line structures
  let activeLineIndex = -1;
  let activeWordIndex = -1;

  // ─── Web Audio API Globals ───
  let audioContext = null;
  let analyser = null;
  let dataArray = null;
  let audioSource = null;

  // ─── Game State ───
  let gameLoaded = false;
  let isPlaying = false;
  let score = 0;
  let combo = 0;
  let maxCombo = 0;
  let shield = SHIELD_MAX;
  let targetSpeedKmh = 120;
  let currentSpeedKmh = 0;
  let cameraShake = 0.0;
  let globalChromaColor = new THREE.Color(0x6366f1);
  let currentSongAnalysis = null;
  let autoPilot = false;
  let animationFrameId = null;

  // Stats for summary
  let statsCount = { perfect: 0, great: 0, good: 0, miss: 0 };

  // Control input states
  let keyboardLane = 1;        // 0=Left, 1=Center, 2=Right
  let mouseMode = true;        // Dynamic mouse steering or lane switching
  let mouseNormalizedX = 0.0;  // -1.0 to 1.0

  // ─── Pitch-to-Color Palette ───
  const CHROMA_COLORS = [
    new THREE.Color(0xff073a), // C: Red
    new THREE.Color(0xff5e00), // C#: Orange-Red
    new THREE.Color(0xffb700), // D: Gold/Yellow
    new THREE.Color(0xaaff00), // D#: Lime
    new THREE.Color(0x39ff14), // E: Neon Green
    new THREE.Color(0x00ffaa), // F: Cyan-Green
    new THREE.Color(0x00f0ff), // F#: Cyan
    new THREE.Color(0x0072ff), // G: Deep Blue
    new THREE.Color(0x7b00ff), // G#: Purple-Blue
    new THREE.Color(0x9d00ff), // A: Purple
    new THREE.Color(0xff007f), // A#: Pink/Magenta
    new THREE.Color(0xff00c8)  // B: Hot Pink
  ];

  // ─── Init Scene ───
  function initThree() {
    // 1. Create Scene & Exp2 Fog
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x020308);
    scene.fog = new THREE.FogExp2(0x020308, 0.0075);

    // 2. Create Camera
    camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 1000);

    // 3. Create Renderer
    renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    // 4. Lights
    const ambientLight = new THREE.AmbientLight(0x0e122d, 0.4);
    scene.add(ambientLight);

    const dirLight = new THREE.DirectionalLight(0xffffff, 0.8);
    dirLight.position.set(0, 30, 20);
    scene.add(dirLight);

    // 5. Starfield Particles
    createStarfield();

    // 6. Handle resize
    window.addEventListener('resize', onWindowResize);
  }

  function createStarfield() {
    const starCount = 1200;
    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array(starCount * 3);
    const colors = new Float32Array(starCount * 3);

    for (let i = 0; i < starCount; i++) {
      // Cylindrical distribution around track Z path
      const angle = Math.random() * Math.PI * 2;
      const radius = 25.0 + Math.random() * 80.0;
      positions[i * 3] = Math.cos(angle) * radius;
      positions[i * 3 + 1] = Math.sin(angle) * radius;
      positions[i * 3 + 2] = -Math.random() * 1200.0; // Extend deep into Z

      // Neon stars
      const color = CHROMA_COLORS[Math.floor(Math.random() * 12)];
      colors[i * 3] = color.r;
      colors[i * 3 + 1] = color.g;
      colors[i * 3 + 2] = color.b;
    }

    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));

    const material = new THREE.PointsMaterial({
      size: 1.2,
      vertexColors: true,
      transparent: true,
      opacity: 0.8,
      sizeAttenuation: true
    });

    starField = new THREE.Points(geometry, material);
    scene.add(starField);
  }

  function onWindowResize() {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  }

  // ─── Setup Web Audio API Synthesizer ───
  function initAudioGraph() {
    if (audioContext) return;
    
    // Create audio context
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    audioContext = new AudioContextClass();
    
    // Create Analyser
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 512;
    dataArray = new Uint8Array(analyser.frequencyBinCount);
    
    // Connect source
    audioSource = audioContext.createMediaElementSource(bgAudio);
    audioSource.connect(analyser);
    analyser.connect(audioContext.destination);
  }

  function playSynthHit(type) {
    if (!audioContext) return;
    
    // Resume if suspended
    if (audioContext.state === 'suspended') {
      audioContext.resume();
    }
    
    const now = audioContext.currentTime;
    
    if (type === 'perfect' || type === 'great' || type === 'good') {
      // 1. Success Chime - Triangular pluck + Sine ring
      const osc1 = audioContext.createOscillator();
      const osc2 = audioContext.createOscillator();
      const gain = audioContext.createGain();
      
      osc1.connect(gain);
      osc2.connect(gain);
      gain.connect(audioContext.destination);
      
      const freq = type === 'perfect' ? 880 : (type === 'great' ? 660 : 440);
      
      osc1.type = 'triangle';
      osc1.frequency.setValueAtTime(freq, now);
      osc1.frequency.exponentialRampToValueAtTime(freq * 1.5, now + 0.12);
      
      osc2.type = 'sine';
      osc2.frequency.setValueAtTime(freq * 2, now);
      
      gain.gain.setValueAtTime(0.18, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.18);
      
      osc1.start(now);
      osc2.start(now);
      
      osc1.stop(now + 0.2);
      osc2.stop(now + 0.2);
      
    } else if (type === 'miss' || type === 'damage') {
      // 2. Collision Damage Buzz - Sawtooth falling pitch
      const osc = audioContext.createOscillator();
      const gain = audioContext.createGain();
      
      osc.connect(gain);
      gain.connect(audioContext.destination);
      
      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(120, now);
      osc.frequency.linearRampToValueAtTime(45, now + 0.25);
      
      gain.gain.setValueAtTime(0.25, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.3);
      
      osc.start(now);
      osc.stop(now + 0.35);
    }
  }

  // ─── Fetch and Load Songs List ───
  async function loadSongsMenu() {
    try {
      const resp = await fetch('/api/songs');
      const songs = await resp.json();
      
      songSelect.innerHTML = '';
      if (songs.length === 0) {
        songSelect.innerHTML = '<option value="">无歌曲 — 请运行 prepare.js</option>';
        return;
      }
      
      // Filter: only show songs that have audio, alignment, AND have been analyzed by audio_analyzer.py
      const playableSongs = songs.filter(s => s.hasAudio && s.hasAlignment && s.hasAnalysis);
      
      if (playableSongs.length === 0) {
        songSelect.innerHTML = '<option value="">无已分析的歌曲 — 请运行 audio_analyzer.py</option>';
        return;
      }
      
      songSelect.innerHTML = '<option value="">选择星际航线 (歌曲)...</option>';
      for (const s of playableSongs) {
        const opt = document.createElement('option');
        opt.value = s.name;
        opt.textContent = `${s.name} ${s.imageCount ? '· 🖼' + s.imageCount : ''}`;
        songSelect.appendChild(opt);
      }
      
      // Auto select first playable song
      if (songSelect.options.length > 1) {
        songSelect.selectedIndex = 1;
        loadSongData(songSelect.value);
      }
    } catch (e) {
      songSelect.innerHTML = '<option value="">连接服务器失败</option>';
    }
  }

  songSelect.addEventListener('change', () => {
    const name = songSelect.value;
    if (name) loadSongData(name);
  });

  // ─── Load Song alignment and analysis ───
  async function loadSongData(songName) {
    songTitle.textContent = songName;
    songBpm.textContent = '载入分析中...';
    gameLoaded = false;
    
    try {
      // 1. Fetch analysis JSON
      const analysisResp = await fetch(`/songs/${encodeURIComponent(songName)}/analysis.json`);
      if (!analysisResp.ok) throw new Error('未检测到 analysis.json，请确保已为该歌曲执行 audio_analyzer.py 并在后台运行了 prepare.js');
      const analysis = await analysisResp.json();
      
      // 2. Fetch alignment JSON
      const alignResp = await fetch(`/songs/${encodeURIComponent(songName)}/alignment.json`);
      const alignment = await alignResp.json();
      
      // 3. Setup audio src
      bgAudio.src = `/songs/${encodeURIComponent(songName)}/audio`;
      bgAudio.load();
      
      // 4. Update menu background if storyboard covers are present
      const songsResp = await fetch('/api/songs');
      const songs = await songsResp.json();
      const songMeta = songs.find(s => s.name === songName);

      if (songMeta && songMeta.imageCount && songMeta.imageFiles && songMeta.imageFiles.length > 0) {
        const coverImg = `/songs/${encodeURIComponent(songName)}/images/${encodeURIComponent(songMeta.imageFiles[0])}`;
        gameBgLayer.style.backgroundImage = `url("${coverImg}")`;
      } else {
        gameBgLayer.style.backgroundImage = 'none';
      }
      
      // 5. Build 3D Track Geometry and Spawn Notes
      build3DLevel(analysis, alignment);
      
      songBpm.textContent = `BPM: ${analysis.bpm.toFixed(1)}`;
      gameLoaded = true;
    } catch (e) {
      songBpm.textContent = `加载失败: ${e.message}`;
      alert(`加载失败:\n${e.message}`);
    }
  }

  // ─── Build 3D Level Spline & Populate Objects ───
  function build3DLevel(analysis, alignment) {
    currentSongAnalysis = analysis;
    // Cleanup previous entities
    cleanup3DLevel();

    // 1. Generate core 3D Spline Path
    const points = [];
    analysis.track_points.forEach(tp => {
      // Map 2D path offset dynamically in 3D: Z direction is progression
      const x = tp.x * 0.65;
      const y = tp.y * 0.45;
      const z = -tp.time * BASE_SPEED;
      points.push(new THREE.Vector3(x, y, z));
    });
    
    // Fallback if too few points
    if (points.length < 2) {
      points.push(new THREE.Vector3(0, 0, 0));
      points.push(new THREE.Vector3(0, 0, -100));
    }
    
    trackCurve = new THREE.CatmullRomCurve3(points);

    // 2. Generate 3 Lane Lines (Tubular rails)
    generateLanes();

    // 3. Generate Spacecraft
    createSpacecraft();

    // 4. Pre-create 3D Equalizer visualizer columns along the track sides
    createTracksideEqualizer();

    // 5. Generate Game Objects: Lyric Crystals, Spikes, Hat Boosters
    generateNoteObjects(analysis, alignment);

    // 6. Preload lyrics subtitle sequences
    setupLyricsSubtitle(alignment);
  }

  function cleanup3DLevel() {
    // Remove old tracks
    laneLines.forEach(l => scene.remove(l));
    laneLines = [];
    laneCurves = [];

    // Remove old spacecraft
    if (shipGroup) {
      scene.remove(shipGroup);
      shipGroup = null;
    }

    // Remove old Equalizers
    visualizerPillars.forEach(p => scene.remove(p));
    visualizerPillars = [];

    // Remove old notes
    activeGameObjects.forEach(obj => scene.remove(obj.mesh));
    activeGameObjects = [];
  }

  function generateLanes() {
    // Generate left, center, and right rail spline offsets
    const laneOffsets = [-LANE_SPACING, 0.0, LANE_SPACING];
    const colors = [0xff007f, 0x00f0ff, 0x9d00ff]; // Left: Magenta, Center: Cyan, Right: Purple

    for (let l = 0; l < 3; l++) {
      const offset = laneOffsets[l];
      const lanePoints = [];
      const steps = 600;
      
      for (let i = 0; i <= steps; i++) {
        const u = i / steps;
        const pos = trackCurve.getPointAt(u);
        const tangent = trackCurve.getTangentAt(u);
        
        // Calculate horizontal normal vector perpendicular to curve tangent and up
        const up = new THREE.Vector3(0, 1, 0);
        const normal = new THREE.Vector3().crossVectors(tangent, up).normalize();
        
        // Shift position horizontally
        const lanePos = pos.clone().addScaledVector(normal, offset);
        lanePoints.push(lanePos);
      }
      
      const lCurve = new THREE.CatmullRomCurve3(lanePoints);
      laneCurves.push(lCurve);

      // Create glowing neon tube geometry for lane
      const tubeGeom = new THREE.TubeGeometry(lCurve, 200, 0.08, 6, false);
      const tubeMat = new THREE.MeshBasicMaterial({
        color: colors[l],
        transparent: true,
        opacity: 0.65
      });
      const tubeMesh = new THREE.Mesh(tubeGeom, tubeMat);
      scene.add(tubeMesh);
      laneLines.push(tubeMesh);
    }
  }

  function createSpacecraft() {
    shipGroup = new THREE.Group();

    // 1. Procedural Fuselage (Main Cone)
    const coneGeom = new THREE.ConeGeometry(0.3, 1.6, 5);
    coneGeom.rotateX(Math.PI / 2); // Point forward
    const metalMat = new THREE.MeshStandardMaterial({
      color: 0x272b38,
      metalness: 0.9,
      roughness: 0.15
    });
    const mainHull = new THREE.Mesh(coneGeom, metalMat);
    shipGroup.add(mainHull);

    // 2. Neon Wings
    const wingGeom = new THREE.BoxGeometry(1.6, 0.05, 0.5);
    const neonCyanMat = new THREE.MeshBasicMaterial({ color: 0x00f0ff });
    const wings = new THREE.Mesh(wingGeom, neonCyanMat);
    wings.position.set(0, -0.1, -0.2);
    shipGroup.add(wings);

    // 3. Tail Thruster ring
    const thrustGeom = new THREE.CylinderGeometry(0.15, 0.15, 0.3, 6);
    thrustGeom.rotateX(Math.PI / 2);
    const orangeEmissive = new THREE.MeshBasicMaterial({ color: 0xffb700 });
    const thruster = new THREE.Mesh(thrustGeom, orangeEmissive);
    thruster.position.set(0, 0, 0.8);
    shipGroup.add(thruster);

    // 4. Ship Headlights (Spotlight to light up road in front)
    const headlight = new THREE.PointLight(0x00f0ff, 2.5, 30);
    headlight.position.set(0, 0.2, -1.5);
    shipGroup.add(headlight);

    // Set initial position
    const startPoint = trackCurve.getPointAt(0);
    shipGroup.position.copy(startPoint);
    scene.add(shipGroup);
  }

  function createTracksideEqualizer() {
    // Generate equalizer pillars along track Z at 5-unit intervals
    const steps = 180;
    const colors = [0x00f0ff, 0xff007f];

    for (let i = 2; i < steps; i++) {
      const u = i / steps;
      const pos = trackCurve.getPointAt(u);
      const tangent = trackCurve.getTangentAt(u);
      
      const up = new THREE.Vector3(0, 1, 0);
      const normal = new THREE.Vector3().crossVectors(tangent, up).normalize();
      
      // Place one pillar left, one pillar right
      const width = 0.4;
      const initialHeight = 1.0;
      const pillarGeom = new THREE.BoxGeometry(width, initialHeight, width);
      pillarGeom.translate(0, initialHeight / 2, 0); // Origin at bottom of box
      
      const leftMat = new THREE.MeshStandardMaterial({
        color: colors[0],
        emissive: colors[0],
        emissiveIntensity: 0.4,
        roughness: 0.2,
        metalness: 0.8
      });
      const rightMat = new THREE.MeshStandardMaterial({
        color: colors[1],
        emissive: colors[1],
        emissiveIntensity: 0.4,
        roughness: 0.2,
        metalness: 0.8
      });

      const pillarLeft = new THREE.Mesh(pillarGeom, leftMat);
      const leftPos = pos.clone().addScaledVector(normal, -LANE_SPACING * 2.5);
      pillarLeft.position.copy(leftPos);
      pillarLeft.lookAt(pillarLeft.position.clone().add(tangent));
      scene.add(pillarLeft);
      visualizerPillars.push({ mesh: pillarLeft, side: 'left', index: i });

      const pillarRight = new THREE.Mesh(pillarGeom, rightMat);
      const rightPos = pos.clone().addScaledVector(normal, LANE_SPACING * 2.5);
      pillarRight.position.copy(rightPos);
      pillarRight.lookAt(pillarRight.position.clone().add(tangent));
      scene.add(pillarRight);
      visualizerPillars.push({ mesh: pillarRight, side: 'right', index: i });
    }
  }

  // ─── Character Canvas Texture Generator ───
  function createCharTexture(char, isLyric = true) {
    const canvas = document.createElement('canvas');
    canvas.width = 128;
    canvas.height = 128;
    const ctx = canvas.getContext('2d');

    // 1. Draw glowing background circle
    ctx.fillStyle = 'rgba(10, 15, 38, 0.85)';
    ctx.beginPath();
    ctx.arc(64, 64, 56, 0, Math.PI * 2);
    ctx.fill();

    // Neon ring stroke
    ctx.strokeStyle = isLyric ? '#ffb700' : '#00f0ff';
    ctx.lineWidth = 4;
    ctx.shadowColor = isLyric ? 'rgba(255, 183, 0, 0.8)' : 'rgba(0, 240, 255, 0.8)';
    ctx.shadowBlur = 12;
    ctx.stroke();

    // 2. Draw Chinese character text in center
    ctx.shadowBlur = 8;
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 64px "Noto Sans SC", sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(char, 64, 64);

    return new THREE.CanvasTexture(canvas);
  }

  function generateNoteObjects(analysis, alignment) {
    // 1. Generate Lyric Note Gems from alignment.json
    let totalChars = 0;
    
    alignment.lines.forEach((line) => {
      const text = line.text.trim();
      const isInterlude = text === '...' || text === '' || text === '[Music]';
      if (isInterlude) return;

      let wordIdx = 0;
      for (let i = 0; i < text.length; i++) {
        const char = text[i];
        if (char === ' ' || char === '\u3000') continue;
        
        // Find character timing matching
        if (wordIdx < line.words.length) {
          const word = line.words[wordIdx];
          const startTime = word.start;
          
          // Generate 3D object at path
          if (startTime > 0.0 && startTime < trackCurve.getLength() / BASE_SPEED) {
            // Distribute lanes deterministically (sweeping pattern)
            const lane = totalChars % 3;
            const laneOffsets = [-LANE_SPACING, 0.0, LANE_SPACING];
            
            // Get position on lane curve
            const u = startTime / (trackCurve.getLength() / BASE_SPEED);
            if (u >= 0.0 && u <= 1.0) {
              const pos = laneCurves[lane].getPointAt(u);
              
              // Create Octahedron Gem with dynamic texture
              const gemGeom = new THREE.OctahedronGeometry(0.55, 0);
              const charTex = createCharTexture(char, true);
              
              const gemMat = new THREE.MeshStandardMaterial({
                map: charTex,
                emissive: 0xffb700,
                emissiveIntensity: 0.35,
                metalness: 0.8,
                roughness: 0.1,
                transparent: true
              });
              
              const gemMesh = new THREE.Mesh(gemGeom, gemMat);
              gemMesh.position.copy(pos);
              scene.add(gemMesh);
              
              activeGameObjects.push({
                type: 'lyric',
                char: char,
                time: startTime,
                lane: lane,
                mesh: gemMesh,
                collected: false
              });
            }
          }
          wordIdx++;
          totalChars++;
        }
      }
    });

    // 2. Generate Spikes & Hat Boosters from analysis.json notes
    const laneOffsets = [-LANE_SPACING, 0.0, LANE_SPACING];
    
    analysis.notes.forEach(note => {
      // Make sure we don't overlap with a lyric note (within 0.25 seconds)
      const nearbyLyric = activeGameObjects.some(obj => obj.type === 'lyric' && Math.abs(obj.time - note.time) < 0.25);
      if (nearbyLyric) return;

      const u = note.time / (trackCurve.getLength() / BASE_SPEED);
      if (u < 0.0 || u > 1.0) return;

      const pos = laneCurves[note.lane].getPointAt(u);

      if (note.type === 'snare') {
        // Red spike cones
        const coneGeom = new THREE.ConeGeometry(0.35, 0.9, 4);
        coneGeom.translate(0, 0.45, 0); // Shift so base rests on lane rail
        
        const spikeMat = new THREE.MeshStandardMaterial({
          color: 0xff073a,
          emissive: 0xff073a,
          emissiveIntensity: 0.6,
          metalness: 0.9,
          roughness: 0.2
        });
        
        const spikeMesh = new THREE.Mesh(coneGeom, spikeMat);
        spikeMesh.position.copy(pos);
        
        // Orient spike perpendicular to lane curve direction
        const tangent = laneCurves[note.lane].getTangentAt(u);
        spikeMesh.lookAt(spikeMesh.position.clone().add(tangent));
        spikeMesh.rotateX(Math.PI / 2); // Lay flat relative to tangent
        
        scene.add(spikeMesh);
        activeGameObjects.push({
          type: 'obstacle',
          time: note.time,
          lane: note.lane,
          mesh: spikeMesh,
          collected: false
        });
        
      } else if (note.type === 'kick') {
        // Small blue rhythm shard
        const shardGeom = new THREE.BoxGeometry(0.3, 0.3, 0.3);
        const shardMat = new THREE.MeshStandardMaterial({
          color: 0x00f0ff,
          emissive: 0x00f0ff,
          emissiveIntensity: 0.5,
          metalness: 0.9,
          roughness: 0.1
        });
        const shardMesh = new THREE.Mesh(shardGeom, shardMat);
        shardMesh.position.copy(pos);
        scene.add(shardMesh);
        
        activeGameObjects.push({
          type: 'kick_shard',
          time: note.time,
          lane: note.lane,
          mesh: shardMesh,
          collected: false
        });
        
      } else if (note.type === 'hat') {
        // Small gold speed crystal
        const speedGeom = new THREE.DodecahedronGeometry(0.2, 0);
        const speedMat = new THREE.MeshStandardMaterial({
          color: 0xffb700,
          emissive: 0xffb700,
          emissiveIntensity: 0.4,
          metalness: 0.5,
          roughness: 0.05
        });
        const speedMesh = new THREE.Mesh(speedGeom, speedMat);
        speedMesh.position.copy(pos);
        scene.add(speedMesh);
        
        activeGameObjects.push({
          type: 'hat_shard',
          time: note.time,
          lane: note.lane,
          mesh: speedMesh,
          collected: false
        });
      }
    });

    // Sort active objects chronologically
    activeGameObjects = sorted(activeGameObjects, x => x.time);
    
    // Sort implementation helper
    function sorted(arr, keyFn) {
      return [...arr].sort((a, b) => keyFn(a) - keyFn(b));
    }
  }

  function setupLyricsSubtitle(alignment) {
    lineTimings = [];
    
    alignment.lines.forEach((line, index) => {
      const text = line.text.trim();
      const isInterlude = text === '...' || text === '' || text === '[Music]';
      
      const lineObj = {
        text,
        start: line.start,
        end: line.end,
        isInterlude,
        words: line.words || [],
        charElements: [] // Will hold DOM refs
      };
      lineTimings.push(lineObj);
    });
  }

  // ─── Input Controls Handling ───
  function initControls() {
    // 1. Keyboard Controls
    document.addEventListener('keydown', (e) => {
      if (!isPlaying) return;
      
      if (e.code === 'KeyA' || e.code === 'ArrowLeft') {
        keyboardLane = Math.max(0, keyboardLane - 1);
        mouseMode = false; // Override mouse steering
        updateShipTargetLane();
      } else if (e.code === 'KeyD' || e.code === 'ArrowRight') {
        keyboardLane = Math.min(2, keyboardLane + 1);
        mouseMode = false;
        updateShipTargetLane();
      }
    });

    // 2. Mouse Controls (smooth steering)
    document.addEventListener('mousemove', (e) => {
      if (!isPlaying) return;
      
      // Calculate normalized X mouse position (-1.0 to 1.0)
      const ratio = e.clientX / window.innerWidth;
      mouseNormalizedX = (ratio - 0.5) * 2.0; // clamp to (-1, 1)
      mouseMode = true;
    });

    // 3. Touch Controls (swipe or tap)
    document.addEventListener('touchmove', (e) => {
      if (!isPlaying) return;
      if (e.touches && e.touches[0]) {
        const ratio = e.touches[0].clientX / window.innerWidth;
        mouseNormalizedX = (ratio - 0.5) * 2.0;
        mouseMode = true;
      }
    });
  }

  function updateShipTargetLane() {
    const laneOffsets = [-LANE_SPACING, 0.0, LANE_SPACING];
    shipTargetX = laneOffsets[keyboardLane];
  }

  // ─── Play / Start Game Flow ───
  async function startGame() {
    if (!gameLoaded) return;
    
    // Init Audio context
    initAudioGraph();
    
    // Reset Stats & Score
    score = 0;
    combo = 0;
    maxCombo = 0;
    shield = SHIELD_MAX;
    statsCount = { perfect: 0, great: 0, good: 0, miss: 0 };
    
    hudScore.textContent = '000,000';
    hudCombo.textContent = '0';
    shieldFill.style.width = '100%';
    
    // Reset Entity visibility
    activeGameObjects.forEach(obj => {
      obj.collected = false;
      obj.mesh.visible = true;
      obj.mesh.scale.set(1, 1, 1);
    });

    // Reset Lyric displays
    activeLineIndex = -1;
    activeWordIndex = -1;
    currentLyric.innerHTML = '航线建立完毕，开始跃迁...';
    nextLyricText.textContent = 'NEXT: --';

    // Hide overlay
    startOverlay.classList.add('hidden');
    resultsOverlay.classList.add('hidden');
    gameBgLayer.style.filter = 'blur(12px) brightness(0.15)'; // Darken menu background
    
    // Play audio
    bgAudio.currentTime = 0;
    try {
      await bgAudio.play();
      isPlaying = true;
      
      // Start loop
      if (animationFrameId) cancelAnimationFrame(animationFrameId);
      animationFrameId = requestAnimationFrame(gameLoop);
    } catch (err) {
      alert(`音频播放失败: ${err.message}`);
      startOverlay.classList.remove('hidden');
    }
  }

  function finishGame() {
    isPlaying = false;
    if (animationFrameId) cancelAnimationFrame(animationFrameId);
    
    // Show results
    document.getElementById('res-score').textContent = score.toLocaleString();
    document.getElementById('res-max-combo').textContent = maxCombo;
    document.getElementById('res-perfect').textContent = statsCount.perfect;
    document.getElementById('res-great').textContent = statsCount.great;
    document.getElementById('res-good').textContent = statsCount.good;
    document.getElementById('res-miss').textContent = statsCount.miss;
    
    resultsOverlay.classList.remove('hidden');
    gameBgLayer.style.filter = 'blur(12px) brightness(0.35)'; // Brighten menu background a bit
    
    playSynthHit('perfect'); // Victory chime
  }

  // ─── Main Game Loop (60 FPS) ───
  function gameLoop() {
    if (!isPlaying) return;

    const t = bgAudio.currentTime;
    const duration = bgAudio.duration || 1.0;
    
    // Check end condition
    if (t >= duration - 0.5) {
      finishGame();
      return;
    }

    // 1. Process Web Audio Analyser (Real-time spectrum)
    let avgBass = 0.0;
    let avgVolume = 0.0;
    if (analyser) {
      analyser.getByteFrequencyData(dataArray);
      
      // Bass range (bins 0 to 12, roughly < 120Hz)
      let bassSum = 0;
      for (let i = 0; i < 12; i++) {
        bassSum += dataArray[i];
      }
      avgBass = (bassSum / 12) / 255.0; // Normalized 0-1
      
      // General Volume (all frequencies)
      let volSum = 0;
      for (let i = 0; i < dataArray.length; i++) {
        volSum += dataArray[i];
      }
      avgVolume = (volSum / dataArray.length) / 255.0;
    }

    // 2. Synchronize target speed & camera shake
    targetSpeedKmh = 100.0 + (avgVolume * 220.0); // Spans 100 - 320 KM/H
    currentSpeedKmh = THREE.MathUtils.lerp(currentSpeedKmh, targetSpeedKmh, 0.1);
    hudSpeed.textContent = `${Math.round(currentSpeedKmh)} KM/H`;

    // 3. Update Camera and Spacecraft positions along spline
    const progress = t / duration;
    
    if (trackCurve && shipGroup) {
      // Position ship at progress time
      const shipPos = trackCurve.getPointAt(progress);
      const tangent = trackCurve.getTangentAt(progress);
      
      const up = new THREE.Vector3(0, 1, 0);
      const normal = new THREE.Vector3().crossVectors(tangent, up).normalize();
      
      // Compute lateral steering offset (lerping from input)
      if (autoPilot) {
        // AI steering: Find closest upcoming note/obstacle in front of the ship
        const laneOffsets = [-LANE_SPACING, 0.0, LANE_SPACING];
        const nextCollectible = activeGameObjects.find(obj => obj.time > t && !obj.collected && obj.type !== 'obstacle');
        const nextObstacle = activeGameObjects.find(obj => obj.time > t && !obj.collected && obj.type === 'obstacle');
        
        let targetLane = keyboardLane;
        
        // 1. Aim for the next collectible (within 1.5 seconds)
        if (nextCollectible && (nextCollectible.time - t) < 1.5) {
          targetLane = nextCollectible.lane;
        }
        
        // 2. Override if there is an obstacle (spike) in our path within 0.8 seconds
        if (nextObstacle && (nextObstacle.time - t) < 0.8) {
          if (nextObstacle.lane === targetLane) {
            // Dodge to an alternate lane!
            if (nextObstacle.lane === 1) {
              targetLane = 0; // If spike is center, go Left
            } else if (nextObstacle.lane === 0) {
              targetLane = 1; // If spike is Left, go Center
            } else if (nextObstacle.lane === 2) {
              targetLane = 1; // If spike is Right, go Center
            }
          }
        }
        
        keyboardLane = targetLane;
        shipTargetX = laneOffsets[targetLane];
      } else if (mouseMode) {
        // Smooth analog steering matching mouse position
        shipTargetX = mouseNormalizedX * LANE_SPACING * 1.35;
      }
      
      const rollAngle = (shipCurrentX - shipTargetX) * 0.15; // ship tilts on change
      shipCurrentX = THREE.MathUtils.lerp(shipCurrentX, shipTargetX, 0.15);
      
      // Set ship position
      const finalShipPos = shipPos.clone().addScaledVector(normal, shipCurrentX);
      shipGroup.position.copy(finalShipPos);
      
      // Rotate ship to look forward down tangent
      const lookAheadProg = Math.min(1.0, progress + LOOK_AHEAD_TIME / duration);
      const lookAheadPos = trackCurve.getPointAt(lookAheadProg);
      const lookAheadTangent = trackCurve.getTangentAt(lookAheadProg);
      const lookAheadNormal = new THREE.Vector3().crossVectors(lookAheadTangent, up).normalize();
      const finalLookPos = lookAheadPos.clone().addScaledVector(lookAheadNormal, shipTargetX); // Look towards target X lane
      
      shipGroup.lookAt(finalLookPos);
      shipGroup.rotateZ(rollAngle); // Apply roll rotation

      // 4. Update Camera following behind
      const camLagProgress = Math.max(0.0, progress - 0.05); // slightly behind ship
      const camTrackPos = trackCurve.getPointAt(camLagProgress);
      const camTangent = trackCurve.getTangentAt(camLagProgress);
      const camNormal = new THREE.Vector3().crossVectors(camTangent, up).normalize();
      
      // Camera sits closer behind the spacecraft
      const idealCamPos = camTrackPos.clone()
        .addScaledVector(camNormal, shipCurrentX * 0.75) // camera tracks ship horizontally
        .addScaledVector(camTangent, -7.5) // 7.5 units behind (closer!)
        .add(new THREE.Vector3(0, 2.4, 0)); // 2.4 units above (closer!)
        
      // Camera shake from bass
      cameraShake = Math.max(0.0, cameraShake * 0.9);
      const shakeOffset = new THREE.Vector3(
        (Math.random() - 0.5) * cameraShake,
        (Math.random() - 0.5) * cameraShake,
        (Math.random() - 0.5) * cameraShake
      );
      
      camera.position.copy(idealCamPos).add(shakeOffset);
      camera.lookAt(shipGroup.position.clone().add(new THREE.Vector3(0, 0.4, -1.0))); // Look slightly in front of ship
    }

    // 5. Animate dynamic visualizer pillars
    updatePillars(avgVolume, progress);

    // 6. Starfield particle speed
    if (starField) {
      starField.rotation.z += 0.001;
      const positions = starField.geometry.attributes.position.array;
      const count = positions.length / 3;
      
      // Stream stars past the player
      for (let i = 0; i < count; i++) {
        positions[i * 3 + 2] += (currentSpeedKmh / 120.0) * 2.0; // speed up based on audio
        if (positions[i * 3 + 2] > 0.0) {
          positions[i * 3 + 2] = -1200.0; // Wrap around to deep background
        }
      }
      starField.geometry.attributes.position.needsUpdate = true;
    }

    // 7. Update active game object positions (rotating notes, etc) and handle collisions
    updateAndCheckCollisions(t);

    // 8. Update lyric subtitles at bottom
    updateLyrics(t);

    // 9. Update ambient color spectrum based on chroma data in track points
    updateAmbientLightColors(t, duration);

    // Render WebGL
    renderer.render(scene, camera);

    // Continue loop
    animationFrameId = requestAnimationFrame(gameLoop);
  }

  function updatePillars(avgVolume, progress) {
    // We scale the height of pillars around the ship's current location
    visualizerPillars.forEach(pillar => {
      // Only scale pillars that are visible (near ship's progress)
      const dist = Math.abs((pillar.index / 180.0) - progress);
      if (dist < 0.25) {
        // Base scale + frequency response
        const scaleVal = 0.5 + (avgVolume * 4.5);
        pillar.mesh.scale.set(1.0, scaleVal, 1.0);
        
        // Emissive intensity beats
        pillar.mesh.material.emissiveIntensity = 0.2 + avgVolume * 0.8;
      }
    });
  }

  function updateAndCheckCollisions(currentTime) {
    const laneOffsets = [-LANE_SPACING, 0.0, LANE_SPACING];
    
    activeGameObjects.forEach(obj => {
      if (obj.collected) return;

      // Animate floating rotation
      if (obj.type === 'lyric') {
        obj.mesh.rotation.y += 0.02;
        obj.mesh.rotation.x += 0.01;
      } else if (obj.type === 'kick_shard' || obj.type === 'hat_shard') {
        obj.mesh.rotation.y += 0.04;
      }

      // Check Z distance to spaceship
      const timeDiff = obj.time - currentTime;
      
      // If the item is in range for collision checking
      if (Math.abs(timeDiff) < 0.1) {
        // Find which lane the ship is in currently
        // Ship lane mapping from X: Left < -1.1, Right > 1.1, Center in between
        let shipLane = 1; // default Center
        if (shipCurrentX < -1.0) shipLane = 0;
        else if (shipCurrentX > 1.0) shipLane = 2;
        
        // If in same lane, check hit!
        if (shipLane === obj.lane) {
          triggerHit(obj, Math.abs(timeDiff));
        }
      }
      
      // If object passed behind the ship and wasn't collected
      if (timeDiff < -0.15 && !obj.collected) {
        obj.collected = true;
        obj.mesh.visible = false;
        
        // Miss! (Only lyrics break combos; missed spikes/kicks are harmless)
        if (obj.type === 'lyric') {
          triggerMiss();
        }
      }
    });
  }

  function triggerHit(obj, absDelta) {
    obj.collected = true;
    obj.mesh.visible = false; // Hide

    // Particle flash scale animation in 3D
    const burst = new THREE.BoxGeometry(1.2, 1.2, 1.2);
    const color = obj.type === 'obstacle' ? 0xff073a : (obj.type === 'lyric' ? 0xffb700 : 0x00f0ff);
    const burstMat = new THREE.MeshBasicMaterial({ color: color, wireframe: true });
    const burstMesh = new THREE.Mesh(burst, burstMat);
    burstMesh.position.copy(obj.mesh.position);
    scene.add(burstMesh);
    
    // Fade out burst mesh
    let opacity = 1.0;
    const fade = () => {
      opacity -= 0.1;
      if (opacity <= 0.0) {
        scene.remove(burstMesh);
      } else {
        burstMesh.scale.addScalar(0.1);
        requestAnimationFrame(fade);
      }
    };
    fade();

    if (obj.type === 'obstacle') {
      // Hitting a red spike
      shield = Math.max(0, shield - 20);
      shieldFill.style.width = `${shield}%`;
      combo = 0;
      hudCombo.textContent = combo;
      
      cameraShake = 0.5; // Heavy camera shake
      triggerJudgmentDisplay('miss');
      playSynthHit('damage');
      
      // Edge flash red
      screenFlash.className = 'active';
      setTimeout(() => screenFlash.className = '', 300);
      
      // Game Over if shield reaches 0
      if (shield <= 0) {
        finishGame();
      }
    } else {
      // Hit a scoring item!
      let judgment = 'perfect';
      let points = 100;
      
      // Grade hit based on timing accuracy
      if (absDelta < 0.04) {
        judgment = 'perfect';
        points = 100;
        statsCount.perfect++;
      } else if (absDelta < 0.08) {
        judgment = 'great';
        points = 80;
        statsCount.great++;
      } else {
        judgment = 'good';
        points = 50;
        statsCount.good++;
      }
      
      // Combo multiplier
      combo++;
      if (combo > maxCombo) maxCombo = combo;
      hudCombo.textContent = combo;
      
      const scoreAdd = points * (1 + Math.floor(combo / 10) * 0.1); // +10% score per 10 combo
      score += Math.round(scoreAdd);
      hudScore.textContent = score.toLocaleString('en-US', { minimumIntegerDigits: 6, useGrouping: true });
      
      triggerJudgmentDisplay(judgment);
      playSynthHit(judgment);
      
      // Gentle camera shake
      cameraShake = judgment === 'perfect' ? 0.08 : 0.04;

      // Handle lyric collected state
      if (obj.type === 'lyric') {
        markLyricCharCollected(obj.char);
      }
    }
  }

  function triggerMiss() {
    combo = 0;
    hudCombo.textContent = combo;
    statsCount.miss++;
    triggerJudgmentDisplay('miss');
  }

  function triggerJudgmentDisplay(judgment) {
    judgmentDisplay.textContent = judgment.toUpperCase();
    judgmentDisplay.className = `hit-${judgment}`;
    
    // Clear animation after a while
    setTimeout(() => {
      if (judgmentDisplay.className === `hit-${judgment}`) {
        judgmentDisplay.className = '';
      }
    }, 350);
  }

  // ─── Lyric sub-characters synchronization ───
  function updateLyrics(currentTime) {
    let activeIndex = -1;
    
    for (let i = 0; i < lineTimings.length; i++) {
      const line = lineTimings[i];
      if (currentTime >= line.start && currentTime < line.end) {
        activeIndex = i;
        break;
      }
    }
    
    if (activeIndex === -1) {
      // Check if we are between lines
      for (let i = lineTimings.length - 1; i >= 0; i--) {
        if (currentTime >= lineTimings[i].end) {
          activeIndex = i;
          break;
        }
      }
    }
    
    if (activeIndex !== activeLineIndex && activeIndex >= 0) {
      activeLineIndex = activeIndex;
      renderActiveLyricLine(lineTimings[activeLineIndex]);
      
      // Show next preview
      if (activeLineIndex + 1 < lineTimings.length) {
        nextLyricText.textContent = `NEXT: ${lineTimings[activeLineIndex + 1].text}`;
      } else {
        nextLyricText.textContent = 'NEXT: --';
      }
    }
    
    // Highlight characters as they are sung (for visual indicator on HUD)
    if (activeLineIndex >= 0) {
      const line = lineTimings[activeLineIndex];
      if (!line.isInterlude) {
        line.words.forEach((w, wi) => {
          if (currentTime >= w.start && currentTime < w.end) {
            const spans = currentLyric.querySelectorAll('span');
            if (spans[wi]) {
              spans[wi].classList.add('active');
            }
          }
        });
      }
    }
  }

  function renderActiveLyricLine(line) {
    currentLyric.innerHTML = '';
    activeLyricSpans = [];
    
    if (line.isInterlude) {
      currentLyric.innerHTML = `<span style="font-style: italic; color: rgba(255,255,255,0.25);">•• 间奏 ••</span>`;
      return;
    }
    
    // Split into characters and wrap in spans
    const chars = Array.from(line.text.trim());
    let wordIdx = 0;
    
    chars.forEach(ch => {
      if (ch === ' ' || ch === '\u3000') {
        const space = document.createElement('span');
        space.innerHTML = '&nbsp;';
        currentLyric.appendChild(space);
      } else {
        const span = document.createElement('span');
        span.textContent = ch;
        currentLyric.appendChild(span);
        activeLyricSpans.push(span);
      }
    });
  }

  function markLyricCharCollected(char) {
    if (activeLineIndex < 0 || activeLyricSpans.length === 0) return;
    
    // Find the matching character in the current subtitle row and mark it
    // Iterate from left to right to find first uncollected match
    for (let i = 0; i < activeLyricSpans.length; i++) {
      const span = activeLyricSpans[i];
      if (span.textContent === char && !span.classList.contains('collected')) {
        span.classList.add('collected');
        break;
      }
    }
  }

  // ─── Color Sync with Pitch (Chroma CQT vector) ───
  function updateAmbientLightColors(currentTime, duration) {
    if (!currentSongAnalysis || !currentSongAnalysis.track_points) return;
    
    const frameIdx = Math.floor(currentTime * 20);
    const tp = currentSongAnalysis.track_points[Math.min(currentSongAnalysis.track_points.length - 1, Math.max(0, frameIdx))];
    if (!tp || !tp.chroma) return;
    
    // Find dominant pitch class
    let maxVal = 0.0;
    let domPitchIdx = 0;
    for (let i = 0; i < 12; i++) {
      if (tp.chroma[i] > maxVal) {
        maxVal = tp.chroma[i];
        domPitchIdx = i;
      }
    }
    
    // Find target chroma color
    const targetColor = CHROMA_COLORS[domPitchIdx];
    
    // Smoothly lerp global ambient color towards the target
    globalChromaColor.lerp(targetColor, 0.08);
    
    // Apply this color to the ambient scene light and fog!
    if (scene.fog) {
      scene.fog.color.copy(globalChromaColor).multiplyScalar(0.08); // Keep fog dark but tinted
    }
    
    // Change lane lines emissive intensity or colors slightly
    laneLines.forEach((lane, i) => {
      // Modify opacity or material color slightly to pulsate to pitch
      lane.material.opacity = 0.5 + Math.sin(currentTime * 4.0 + i) * 0.15;
    });
  }

  // ─── Setup Events and Event Handlers ───
  function initEventBindings() {
    btnStart.addEventListener('click', startGame);
    
    btnRestart.addEventListener('click', () => {
      resultsOverlay.classList.add('hidden');
      startGame();
    });
    
    btnBackMenu.addEventListener('click', () => {
      resultsOverlay.classList.add('hidden');
      startOverlay.classList.remove('hidden');
      gameBgLayer.style.filter = 'blur(12px) brightness(0.2)';
    });

    const btnAutopilot = document.getElementById('btn-autopilot');
    btnAutopilot.addEventListener('click', () => {
      autoPilot = !autoPilot;
      if (autoPilot) {
        btnAutopilot.classList.add('active');
        btnAutopilot.textContent = '🤖 自动驾驶: 开';
      } else {
        btnAutopilot.classList.remove('active');
        btnAutopilot.textContent = '🤖 自动驾驶: 关';
      }
    });
  }

  // ─── Entry Point ───
  function main() {
    initThree();
    initControls();
    initEventBindings();
    loadSongsMenu();
  }

  window.onload = main;

})();
