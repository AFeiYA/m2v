/**
 * m2v: Deterministic Motion Runtime (Pdoom-Grade Edition)
 * ============================================================================
 * 纯确定性运动运行时内核与预设求值器
 * 核心特性:
 *   1. Frame = F(t, scene, assets, seed) - 绝对时间纯函数寻址，无跨帧累加，防切后台音画漂移
 *   2. Audio Master Clock & Groove Engine - 节拍 (BPM) 脉冲、鼓点 (Kick/Snare) 瞬态冲击与后坐力
 *   3. Syllable-Level Kinetic Pop - 音节/逐字卡点弹跳、高亮与爆闪，声画精准咬合
 *   4. Pdoom 3D Spatial Staging - 无限透视地平线网格 (Horizon Grid)、摄像机震颤 (Recoil Shake)、色散 (Chromatic Aberration)
 * ============================================================================
 */

(function (root, factory) {
  if (typeof define === 'function' && define.amd) {
    define([], factory);
  } else if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.DeterministicMotionRuntime = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {

  // ---------------------------------------------------------------------------
  // 1. 确定性哈希伪随机数发生器 (Seeded PRNG)
  // ---------------------------------------------------------------------------
  function hashString(str) {
    let hash = 2166136261 >>> 0;
    for (let i = 0; i < str.length; i++) {
      hash ^= str.charCodeAt(i);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }

  function seededRandom(seedStr, min = 0, max = 1) {
    const seed = hashString(String(seedStr || 'm2v:default_seed'));
    let t = (seed + 0x6D2B79F5) >>> 0;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    const rand = ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    return min + rand * (max - min);
  }

  // ---------------------------------------------------------------------------
  // 2. 物理缓动与插值数学库 (Easing Math)
  // ---------------------------------------------------------------------------
  const Easing = {
    linear: (t) => Math.max(0, Math.min(1, t)),
    easeOutCubic: (t) => {
      const p = Math.max(0, Math.min(1, t));
      return 1 - Math.pow(1 - p, 3);
    },
    easeOutExpo: (t) => {
      const p = Math.max(0, Math.min(1, t));
      return p === 1 ? 1 : 1 - Math.pow(2, -10 * p);
    },
    easeInOutCubic: (t) => {
      const p = Math.max(0, Math.min(1, t));
      return p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
    },
    easeOutOvershoot: (t, s = 1.70158) => {
      const p = Math.max(0, Math.min(1, t)) - 1;
      return p * p * ((s + 1) * p + s) + 1;
    },
    clamp: (val, min, max) => Math.max(min, Math.min(max, val)),
    lerp: (a, b, t) => a + (b - a) * Math.max(0, Math.min(1, t)),
  };

  // ---------------------------------------------------------------------------
  // 3. 预设注册中心 (Preset Registry: 纯数学状态计算，严禁操作 DOM)
  // ---------------------------------------------------------------------------
  const Presets = {
    /**
     * ⚡ 赛博空间暴击 (Pdoom Cyber 3D)
     * - 灵感源自 I'm Upping My P(doom)
     * - 极端体量反差、透视地平线网格、重低音摄像机震颤、RGB 色散爆炸
     */
    pdoom_cyber: {
      name: '赛博空间暴击 (Pdoom Cyber 3D)',
      hasGrid: true,
      gridColor: 'rgba(0, 240, 255, 0.45)',
      evaluate(cue, t, seed, groove) {
        const start = cue.start;
        const end = cue.end;
        const dur = Math.max(0.1, end - start);
        const emphasis = cue.emphasis !== undefined ? cue.emphasis : 0.85;

        const leadIn = 0.14;
        const leadOut = 0.20;
        const windowStart = start - leadIn;
        const windowEnd = end + leadOut;

        if (t < windowStart || t > windowEnd) {
          return { visible: false };
        }

        let scale = 1.0;
        let opacity = 1.0;
        let z = 0;
        let rot = seededRandom(`${seed}:rot`, -4.0, 4.0);

        if (t < start) {
          // Slam Zoom 入场: 从 2.4 倍超大体量贴脸瞬间撞击停驻
          const progress = Easing.easeOutExpo((t - windowStart) / leadIn);
          scale = Easing.lerp(2.4, 1.0, progress);
          opacity = Easing.lerp(0.0, 1.0, progress);
          z = Easing.lerp(200, 0, progress);
          rot = Easing.lerp(rot * 2.5, rot, progress);
        } else if (t <= end) {
          // 活跃期: 随音频重低音脉冲产生微弹跳
          const kickBoost = groove ? groove.kickImpulse * 0.12 : 0;
          const beatBoost = groove ? groove.beatBounce * 0.03 : 0;
          scale = 1.0 + kickBoost + beatBoost;
          opacity = 1.0;
          z = 0;
        } else {
          // 极速退场: 向纵深穿梭飞出
          const exitProgress = Easing.easeOutCubic((t - end) / leadOut);
          scale = Easing.lerp(1.0, 0.65, exitProgress);
          opacity = Easing.lerp(1.0, 0.0, exitProgress);
          z = Easing.lerp(0, -180, exitProgress);
        }

        const isHero = cue.role === 'hero' || emphasis >= 0.8;
        const baseColor = isHero ? '#00F0FF' : '#E2E8F0';
        const activeColor = '#FFFFFF';

        // 鼓点色散偏移计算
        const split = groove && groove.kickImpulse > 0.15 ? Math.round(groove.kickImpulse * 8) : 0;
        let textShadow = '0 0 20px rgba(0, 240, 255, 0.6), 0 0 40px rgba(0, 240, 255, 0.3)';
        if (split > 0) {
          textShadow = `-${split}px 0 rgba(255, 0, 80, 0.85), ${split}px 0 rgba(0, 240, 255, 0.85), 0 0 24px rgba(0, 240, 255, 0.9)`;
        }

        return {
          visible: true,
          text: cue.text,
          words: cue.words || [],
          scale: scale,
          z: z,
          rotation: rot,
          opacity: opacity,
          fontWeight: 900,
          fontFamily: "'Impact', 'Arial Black', -apple-system, sans-serif",
          color: baseColor,
          activeColor: activeColor,
          letterSpacing: '0.04em',
          textTransform: 'uppercase',
          textShadow: textShadow,
          isHero: isHero,
          split: split,
        };
      },
    },

    /**
     * 🖤 瑞士先锋大字 (Swiss Minimal)
     * - 超大字体、现代排版、字重突变、上下视差错位推挤
     */
    swiss_minimal: {
      name: '瑞士先锋大字 (Swiss Minimal)',
      hasGrid: false,
      evaluate(cue, t, seed, groove) {
        const start = cue.start;
        const end = cue.end;
        const dur = Math.max(0.1, end - start);
        const emphasis = cue.emphasis !== undefined ? cue.emphasis : 0.7;

        const leadIn = 0.18;
        const leadOut = 0.22;
        const windowStart = start - leadIn;
        const windowEnd = end + leadOut;

        if (t < windowStart || t > windowEnd) {
          return { visible: false };
        }

        let y = 0;
        let scale = 1.0;
        let opacity = 1.0;
        let fontWeight = 500;

        if (t < start) {
          const progress = Easing.easeOutCubic((t - windowStart) / leadIn);
          y = Easing.lerp(35, 0, progress);
          opacity = Easing.lerp(0.0, 1.0, progress);
          scale = Easing.lerp(0.94, 1.0, progress);
          fontWeight = 400;
        } else if (t <= end) {
          const kickBoost = groove ? groove.kickImpulse * 0.08 : 0;
          scale = 1.0 + kickBoost;
          fontWeight = emphasis > 0.75 ? 900 : 700;
          y = 0;
          opacity = 1.0;
        } else {
          const exitProgress = Easing.easeInOutCubic((t - end) / leadOut);
          y = Easing.lerp(0, -32, exitProgress);
          opacity = Easing.lerp(1.0, 0.0, exitProgress);
          scale = Easing.lerp(1.0, 1.05, exitProgress);
          fontWeight = 600;
        }

        const isHero = cue.role === 'hero' || emphasis > 0.8;
        return {
          visible: true,
          text: cue.text,
          words: cue.words || [],
          scale: scale,
          y: y,
          rotation: 0,
          opacity: opacity,
          fontWeight: fontWeight,
          fontFamily: "-apple-system, BlinkMacSystemFont, 'Helvetica Neue', 'PingFang SC', sans-serif",
          color: isHero ? '#FFFFFF' : '#CBD5E1',
          activeColor: '#FFFFFF',
          textShadow: '0 4px 24px rgba(0,0,0,0.85)',
          isHero: isHero,
        };
      },
    },

    /**
     * 🏷️ 街头潮酷贴纸 (Street Pop)
     * - 确定性微倾斜角、撞色粗黑描边、弹性砸入下坠
     */
    street_pop: {
      name: '街头潮酷贴纸 (Street Pop)',
      hasGrid: false,
      evaluate(cue, t, seed, groove) {
        const start = cue.start;
        const end = cue.end;
        const dur = Math.max(0.1, end - start);
        const emphasis = cue.emphasis !== undefined ? cue.emphasis : 0.8;

        const leadIn = 0.16;
        const leadOut = 0.20;
        const windowStart = start - leadIn;
        const windowEnd = end + leadOut;

        if (t < windowStart || t > windowEnd) {
          return { visible: false };
        }

        const rotTarget = seededRandom(`${seed}:rot`, -5.0, 5.0);
        const offsetX = seededRandom(`${seed}:x`, -12, 12);

        let y = 0;
        let scale = 1.0;
        let opacity = 1.0;
        let rot = rotTarget;

        if (t < start) {
          const progress = Easing.easeOutOvershoot((t - windowStart) / leadIn, 2.2);
          y = Easing.lerp(-40, 0, progress);
          scale = Easing.lerp(1.3, 1.0, progress);
          opacity = Easing.lerp(0.0, 1.0, progress);
          rot = Easing.lerp(rotTarget * 2.2, rotTarget, progress);
        } else if (t <= end) {
          const kickBoost = groove ? groove.kickImpulse * 0.12 : 0;
          scale = 1.0 + kickBoost;
          y = 0;
          opacity = 1.0;
          rot = rotTarget;
        } else {
          const exitProgress = Easing.easeOutCubic((t - end) / leadOut);
          y = Easing.lerp(0, 20, exitProgress);
          scale = Easing.lerp(1.0, 0.85, exitProgress);
          opacity = Easing.lerp(1.0, 0.0, exitProgress);
          rot = rotTarget + exitProgress * 4;
        }

        const bgCol = emphasis > 0.85 ? '#FFE600' : (emphasis > 0.7 ? '#FF2A6D' : '#05D9E8');
        const textCol = bgCol === '#FFE600' ? '#0D0E15' : '#FFFFFF';

        return {
          visible: true,
          text: cue.text,
          words: cue.words || [],
          x: offsetX,
          y: y,
          scale: scale,
          rotation: rot,
          opacity: opacity,
          fontWeight: 900,
          fontFamily: "-apple-system, BlinkMacSystemFont, 'Impact', sans-serif",
          color: textCol,
          activeColor: textCol,
          backgroundColor: bgCol,
          padding: '6px 18px',
          borderRadius: '4px',
          boxShadow: '0 8px 24px rgba(0,0,0,0.6)',
          isHero: true,
        };
      },
    },

    /**
     * ✨ 赛博复古流光 (Neon Glow)
     * - 高斯虚实景深切换、柔和光斑漫反射
     */
    neon_glow: {
      name: '复古霓虹流光 (Neon Glow)',
      hasGrid: false,
      evaluate(cue, t, seed, groove) {
        const start = cue.start;
        const end = cue.end;
        const leadIn = 0.25;
        const leadOut = 0.28;
        const windowStart = start - leadIn;
        const windowEnd = end + leadOut;

        if (t < windowStart || t > windowEnd) {
          return { visible: false };
        }

        let opacity = 1.0;
        let blur = 0;
        let scale = 1.0;

        if (t < start) {
          const progress = Easing.easeOutCubic((t - windowStart) / leadIn);
          opacity = Easing.lerp(0.1, 0.9, progress);
          blur = Easing.lerp(8, 0, progress);
          scale = Easing.lerp(0.92, 1.0, progress);
        } else if (t <= end) {
          const kickBoost = groove ? groove.kickImpulse * 0.08 : 0;
          scale = 1.0 + kickBoost;
          opacity = 1.0;
          blur = 0;
        } else {
          const exitProgress = Easing.easeInOutCubic((t - end) / leadOut);
          opacity = Easing.lerp(1.0, 0.0, exitProgress);
          blur = Easing.lerp(0, 10, exitProgress);
          scale = Easing.lerp(1.0, 1.08, exitProgress);
        }

        return {
          visible: true,
          text: cue.text,
          words: cue.words || [],
          scale: scale,
          opacity: opacity,
          blur: blur,
          fontWeight: 700,
          fontFamily: "-apple-system, BlinkMacSystemFont, 'PingFang SC', sans-serif",
          color: '#E0F7FA',
          activeColor: '#FFFFFF',
          textShadow: '0 0 14px #00E5FF, 0 0 32px #00B0FF, 0 0 52px #2979FF',
          letterSpacing: '0.04em',
          isHero: true,
        };
      },
    },
  };

  // ---------------------------------------------------------------------------
  // 4. 空间与音画渲染引擎 (DOM + Perspective Grid Canvas Renderer)
  // ---------------------------------------------------------------------------
  class DOMRenderer {
    constructor(containerElement) {
      this.container = containerElement;
      this.elementPool = new Map(); // cue_id -> HTMLElement
      this.cameraRig = null;
      this.gridCanvas = null;
      this.gridCtx = null;
      this.initContainer();
    }

    initContainer() {
      if (!this.container) return;
      this.container.innerHTML = '';
      this.container.style.position = 'absolute';
      this.container.style.inset = '0';
      this.container.style.pointerEvents = 'none';
      this.container.style.overflow = 'hidden';
      this.container.style.zIndex = '30';

      // 1. 底层 3D 透视地平线画布 (Pdoom Perspective Grid)
      this.gridCanvas = document.createElement('canvas');
      this.gridCanvas.className = 'kinetic-pdoom-grid';
      this.gridCanvas.style.position = 'absolute';
      this.gridCanvas.style.inset = '0';
      this.gridCanvas.style.width = '100%';
      this.gridCanvas.style.height = '100%';
      this.gridCanvas.style.display = 'none';
      this.gridCanvas.style.pointerEvents = 'none';
      this.gridCanvas.style.zIndex = '1';
      this.container.appendChild(this.gridCanvas);
      this.gridCtx = this.gridCanvas.getContext('2d');

      // 2. 核心 3D 摄像机平台 (Camera Rig)
      this.cameraRig = document.createElement('div');
      this.cameraRig.className = 'kinetic-camera-rig';
      this.cameraRig.style.position = 'absolute';
      this.cameraRig.style.inset = '0';
      this.cameraRig.style.display = 'flex';
      this.cameraRig.style.alignItems = 'center';
      this.cameraRig.style.justifyContent = 'center';
      this.cameraRig.style.perspective = '900px';
      this.cameraRig.style.transformStyle = 'preserve-3d';
      this.cameraRig.style.zIndex = '2';
      this.container.appendChild(this.cameraRig);
    }

    /**
     * 绘制 Pdoom 风格无限透视地平线网格
     */
    drawGrid(t, bpm, kickImpulse, gridColor) {
      if (!this.gridCanvas || !this.gridCtx) return;
      const canvas = this.gridCanvas;
      const ctx = this.gridCtx;

      // 动态响应 DPR 与分辨率
      const w = canvas.clientWidth || 800;
      const h = canvas.clientHeight || 450;
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
      }

      ctx.clearRect(0, 0, w, h);

      // 地平线高度设在视野 46% 位置
      const horizonY = h * 0.46;
      const vpX = w * 0.5;

      // 随 BPM 极速流逝的 Z 轴网格位移
      const speed = (bpm / 60) * 160;
      const gridPitch = 40;
      const zOffset = (t * speed) % gridPitch;

      ctx.save();
      ctx.lineWidth = 1.2;

      // 随鼓点过载增强辉光
      const baseAlpha = 0.28 + kickImpulse * 0.45;
      ctx.strokeStyle = gridColor || `rgba(0, 240, 255, ${baseAlpha})`;

      // A. 辐射透视纵向线 (Vanishing Lines)
      const numLines = 18;
      const spread = w * 1.6;
      for (let i = -numLines; i <= numLines; i++) {
        const bottomX = vpX + (i / numLines) * spread;
        ctx.beginPath();
        ctx.moveTo(vpX, horizonY);
        ctx.lineTo(bottomX, h);
        ctx.stroke();
      }

      // B. 指数深度的横向水平线 (Horizontal Perspective Lines)
      const numHoriz = 16;
      for (let j = 0; j < numHoriz; j++) {
        const rawP = (j * gridPitch + zOffset) / (numHoriz * gridPitch);
        const p = Math.max(0, Math.min(1, rawP));
        // 非线性透视映射
        const lineY = horizonY + Math.pow(p, 2.2) * (h - horizonY);
        ctx.beginPath();
        ctx.moveTo(0, lineY);
        ctx.lineTo(w, lineY);
        ctx.stroke();
      }

      // C. 地平线辉光渐变 (Horizon Glow)
      const grad = ctx.createLinearGradient(0, horizonY - 40, 0, horizonY + 60);
      grad.addColorStop(0, 'rgba(0,0,0,0)');
      grad.addColorStop(0.4, `rgba(0, 240, 255, ${0.15 + kickImpulse * 0.3})`);
      grad.addColorStop(1, 'rgba(0,0,0,0)');
      ctx.fillStyle = grad;
      ctx.fillRect(0, horizonY - 40, w, 100);

      ctx.restore();
    }

    /**
     * 更新摄像机后坐力振颤 (Camera Shake & Recoil)
     */
    applyCameraMotion(groove, t) {
      if (!this.cameraRig) return;
      if (!groove || groove.kickImpulse <= 0.01) {
        this.cameraRig.style.transform = 'translate3d(0, 0, 0) scale(1) rotate(0deg)';
        return;
      }

      const impulse = groove.kickImpulse;
      // 确定性瞬态多频简谐震颤
      const shakeX = Math.sin(t * 62.0) * impulse * 14.0;
      const shakeY = Math.cos(t * 53.0) * impulse * 9.0;
      const shakeRot = Math.sin(t * 43.0) * impulse * 1.5;
      const zoom = 1.0 + impulse * 0.05 + (groove.beatBounce || 0) * 0.015;

      this.cameraRig.style.transform = `translate3d(${shakeX.toFixed(2)}px, ${shakeY.toFixed(2)}px, 0) scale(${zoom.toFixed(3)}) rotate(${shakeRot.toFixed(2)}deg)`;
    }

    /**
     * 核心词组与逐音节渲染 (Syllable-Level Pop)
     */
    renderCue(cue, state, currentTime) {
      if (!this.cameraRig) return;
      const cueId = cue.cue_id;

      if (!state.visible) {
        const existing = this.elementPool.get(cueId);
        if (existing) {
          existing.style.display = 'none';
        }
        return;
      }

      let el = this.elementPool.get(cueId);
      if (!el) {
        el = document.createElement('div');
        el.className = 'kinetic-cue-item';
        el.style.position = 'absolute';
        el.style.textAlign = 'center';
        el.style.willChange = 'transform, opacity, filter';
        el.style.transformOrigin = 'center center';
        el.style.whiteSpace = 'nowrap';
        el.style.userSelect = 'none';
        this.cameraRig.appendChild(el);
        this.elementPool.set(cueId, el);
      }

      el.style.display = 'block';

      // 字体规格
      el.style.fontSize = state.isHero
        ? 'clamp(42px, 7.2vw, 108px)'
        : 'clamp(30px, 5.0vw, 76px)';
      el.style.fontWeight = String(state.fontWeight || 800);
      el.style.fontFamily = state.fontFamily || "-apple-system, BlinkMacSystemFont, sans-serif";
      el.style.color = state.color || '#FFFFFF';
      el.style.letterSpacing = state.letterSpacing || 'normal';
      el.style.textTransform = state.textTransform || 'none';
      el.style.opacity = String(state.opacity);
      el.style.filter = state.blur > 0 ? `blur(${state.blur}px)` : 'none';
      el.style.textShadow = state.textShadow || 'none';

      // 背景与包装
      if (state.backgroundColor && state.backgroundColor !== 'transparent') {
        el.style.backgroundColor = state.backgroundColor;
        el.style.padding = state.padding || '6px 18px';
        el.style.borderRadius = state.borderRadius || '6px';
        el.style.boxShadow = state.boxShadow || 'none';
      } else {
        el.style.backgroundColor = 'transparent';
        el.style.padding = '0';
        el.style.boxShadow = 'none';
      }

      // 确定性 3D 几何变换矩阵 (Slam Zoom + Z 轴飞跃)
      const x = state.x || 0;
      const y = state.y || 0;
      const z = state.z || 0;
      const rot = state.rotation || 0;
      const scale = state.scale || 1.0;
      el.style.transform = `translate3d(${x}px, ${y}px, ${z}px) scale(${scale}) rotate(${rot}deg)`;

      // 音节级逐字渲染 (Syllable Kinetic Pop)
      const words = state.words || [];
      if (words.length > 0) {
        // 构建或复用音节 span
        let spans = el.querySelectorAll('.k-syllable');
        if (spans.length !== words.length) {
          el.innerHTML = '';
          for (let i = 0; i < words.length; i++) {
            const span = document.createElement('span');
            span.className = 'k-syllable';
            span.style.display = 'inline-block';
            span.style.transition = 'transform 0.06s ease-out, color 0.08s, opacity 0.08s';
            span.textContent = words[i].word;
            el.appendChild(span);
          }
          spans = el.querySelectorAll('.k-syllable');
        }

        // 求值当前时刻每个字的瞬态音画状态
        for (let i = 0; i < words.length; i++) {
          const w = words[i];
          const span = spans[i];
          const wStart = Number(w.start);
          const wEnd = Number(w.end);

          if (currentTime < wStart) {
            // 未唱到: 弱透明度、微缩小、幽灵待机
            span.style.opacity = '0.25';
            span.style.transform = 'scale(0.92)';
            span.style.color = state.color;
            span.style.textShadow = 'none';
          } else if (currentTime <= wEnd) {
            // 正在唱到 (活跃爆发期!): 瞬态弹跳 + 刺目高亮
            const wDur = Math.max(0.06, wEnd - wStart);
            const wProg = (currentTime - wStart) / wDur;
            // 击打爆发冲量 (前 30% 时间内向上突弹)
            const attackImpulse = wProg < 0.35 ? Math.pow(1.0 - (wProg / 0.35), 2.0) : 0;
            const sylScale = 1.0 + attackImpulse * 0.38;

            span.style.opacity = '1.0';
            span.style.transform = `scale(${sylScale.toFixed(3)}) translateY(${-attackImpulse * 6}px)`;
            span.style.color = state.activeColor || '#FFFFFF';
            span.style.textShadow = state.isHero
              ? '0 0 20px #00F0FF, 0 0 40px #00F0FF, 0 0 60px #FFFFFF'
              : '0 0 16px rgba(255,255,255,0.85)';
          } else {
            // 已唱过: 稳定坚实
            span.style.opacity = '0.92';
            span.style.transform = 'scale(1.0) translateY(0)';
            span.style.color = state.color;
            span.style.textShadow = 'none';
          }
        }
      } else {
        // 无细分词级时间戳，整句文本呈现
        if (el.textContent !== state.text) {
          el.textContent = state.text;
        }
      }
    }

    clear() {
      this.elementPool.forEach((el) => {
        el.style.display = 'none';
      });
      if (this.gridCtx && this.gridCanvas) {
        this.gridCtx.clearRect(0, 0, this.gridCanvas.width, this.gridCanvas.height);
      }
      if (this.cameraRig) {
        this.cameraRig.style.transform = 'translate3d(0, 0, 0) scale(1) rotate(0deg)';
      }
    }

    destroy() {
      this.clear();
      this.elementPool.clear();
      if (this.container) {
        this.container.innerHTML = '';
      }
    }
  }

  // ---------------------------------------------------------------------------
  // 5. 核心确定性运动运行时门面 (DeterministicMotionRuntime)
  // ---------------------------------------------------------------------------
  class DeterministicMotionRuntime {
    constructor(options = {}) {
      this.preset = options.preset || 'pdoom_cyber';
      this.enabled = options.enabled !== undefined ? options.enabled : true;
      this.dsl = null;
      this.scenes = [];
      this.renderer = null;

      // 音频节拍与鼓点特征库
      this.bpm = 120.0;
      this.beats = [];
      this.drumHits = [];

      if (options.container) {
        this.mount(options.container);
      }
    }

    mount(container) {
      const el = typeof container === 'string' ? document.querySelector(container) : container;
      if (!el) {
        console.warn('[DeterministicMotionRuntime] 容器未找到:', container);
        return;
      }
      this.renderer = new DOMRenderer(el);
    }

    setAudioFeatures(features = {}) {
      if (features.bpm) this.bpm = Number(features.bpm);
      if (features.beats) this.beats = features.beats.map(Number);
      if (features.drum_hits) this.drumHits = features.drum_hits;
    }

    setTimeline(dsl) {
      if (!dsl) {
        this.dsl = null;
        this.scenes = [];
        if (this.renderer) this.renderer.clear();
        return;
      }
      this.dsl = dsl;
      this.scenes = dsl.scenes || [];

      // 提取视听元数据
      if (dsl.meta) {
        if (dsl.meta.bpm) this.bpm = Number(dsl.meta.bpm);
        if (dsl.meta.beats) this.beats = dsl.meta.beats.map(Number);
        if (dsl.meta.drum_hits) this.drumHits = dsl.meta.drum_hits;
      }

      if (this.renderer) this.renderer.clear();
    }

    setPreset(presetName) {
      if (Presets[presetName]) {
        this.preset = presetName;
      } else {
        console.warn(`[DeterministicMotionRuntime] 未知预设 ${presetName}, 回退到 pdoom_cyber`);
        this.preset = 'pdoom_cyber';
      }
    }

    setEnabled(enabled) {
      this.enabled = !!enabled;
      if (!this.enabled && this.renderer) {
        this.renderer.clear();
      }
    }

    getPresetList() {
      return Object.keys(Presets).map((key) => ({
        id: key,
        name: Presets[key].name,
      }));
    }

    /**
     * 计算当前时刻的时域音频律动特征 (Groove Engine)
     */
    getAudioGroove(t) {
      const bpm = this.bpm || 120.0;
      const beatInterval = 60.0 / bpm;
      const beatPhase = (t / beatInterval) % 1.0;
      // 连续 4/4 拍呼吸回弹
      const beatBounce = Math.exp(-6.0 * beatPhase);

      // 查找最近一次鼓点打击 (Kick / Snare)
      let kickImpulse = 0;
      let lastHitType = 'kick';

      const hits = this.drumHits || [];
      if (hits.length > 0) {
        // 在前 0.25 秒的时间窗内寻找最近的打击
        for (let i = hits.length - 1; i >= 0; i--) {
          const hit = hits[i];
          const delta = t - Number(hit.time);
          if (delta >= 0 && delta <= 0.24) {
            kickImpulse = Math.exp(-14.0 * delta);
            lastHitType = hit.type || 'kick';
            break;
          } else if (delta > 0.24) {
            break;
          }
        }
      } else if (this.beats.length > 0) {
        // 降级：若无鼓点分离，使用标准拍点 (Beat)
        for (let i = this.beats.length - 1; i >= 0; i--) {
          const bTime = this.beats[i];
          const delta = t - bTime;
          if (delta >= 0 && delta <= 0.22) {
            kickImpulse = Math.exp(-14.0 * delta);
            break;
          } else if (delta > 0.22) {
            break;
          }
        }
      }

      return {
        bpm: bpm,
        beatPhase: beatPhase,
        beatBounce: beatBounce,
        kickImpulse: kickImpulse,
        lastHitType: lastHitType,
      };
    }

    /**
     * 核心纯时间函数入口: 无论何时调用 renderAt(t)，结果绝对恒定
     */
    renderAt(t) {
      if (!this.enabled || !this.renderer || !this.scenes || this.scenes.length === 0) {
        return;
      }

      const currentTime = Math.max(0, Number(t) || 0);
      const activePreset = Presets[this.preset] || Presets.pdoom_cyber;

      // 1. 求值音频时钟律动
      const groove = this.getAudioGroove(currentTime);

      // 2. 绘制 3D 透视网格 (若预设开启)
      if (activePreset.hasGrid) {
        if (this.renderer.gridCanvas) this.renderer.gridCanvas.style.display = 'block';
        this.renderer.drawGrid(currentTime, this.bpm, groove.kickImpulse, activePreset.gridColor);
      } else {
        if (this.renderer.gridCanvas) this.renderer.gridCanvas.style.display = 'none';
      }

      // 3. 应用摄像机后坐力震颤
      this.renderer.applyCameraMotion(groove, currentTime);

      // 4. 寻址包含当前时间的场景
      for (let i = 0; i < this.scenes.length; i++) {
        const scene = this.scenes[i];
        if (currentTime >= scene.start - 0.4 && currentTime <= scene.end + 0.4) {
          const layers = scene.layers || [];
          for (let j = 0; j < layers.length; j++) {
            const layer = layers[j];
            if (layer.type === 'kinetic_typography') {
              const cues = layer.cues || [];
              const layerSeed = layer.seed || `${scene.scene_id}:layer_${j}`;

              for (let k = 0; k < cues.length; k++) {
                const cue = cues[k];
                const cueSeed = `${layerSeed}:${cue.cue_id || k}`;
                // 状态解耦求值
                const motionState = activePreset.evaluate(cue, currentTime, cueSeed, groove);
                // 渲染器绘制 (传递 currentTime 进行音节高精判定)
                this.renderer.renderCue(cue, motionState, currentTime);
              }
            }
          }
        }
      }
    }
  }

  // 静态暴露供外部单测或扩展使用
  DeterministicMotionRuntime.Presets = Presets;
  DeterministicMotionRuntime.SeededPRNG = { hashString, seededRandom };
  DeterministicMotionRuntime.Easing = Easing;

  return DeterministicMotionRuntime;
});
