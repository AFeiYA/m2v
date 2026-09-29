/**
 * m2v: Deterministic Motion Runtime
 * ============================================================================
 * 纯确定性运动运行时内核与预设求值器
 * 核心铁律:
 *   1. Frame = F(t, scene, assets, seed) - 绝对时间纯函数寻址，无跨帧状态递增
 *   2. Seeded Determinism - 严禁 Math.random()，一切倾角位移基于种子哈希
 *   3. Preset.evaluate(cue, t) -> MotionState - 运动数学与 DOM/Canvas 介质完全解耦
 *   4. Audio Master Clock - 播放器时间驱动，防切后台音画漂移
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
    // Mulberry32
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
     * 瑞士先锋大字呼吸流 (Swiss Minimal)
     * - 超大字体、现代排版、字重突变、上下视差错位推挤
     */
    swiss_minimal: {
      name: '瑞士先锋大字 (Swiss Minimal)',
      evaluate(cue, t, seed) {
        const start = cue.start;
        const end = cue.end;
        const dur = Math.max(0.1, end - start);
        const emphasis = cue.emphasis !== undefined ? cue.emphasis : 0.7;

        // 生命周期窗口: 前后各宽限 0.25 秒做转场推移
        const leadIn = 0.22;
        const leadOut = 0.26;
        const windowStart = start - leadIn;
        const windowEnd = end + leadOut;

        if (t < windowStart || t > windowEnd) {
          return { visible: false };
        }

        let y = 0;
        let scale = 1.0;
        let opacity = 1.0;
        let fontWeight = 400;

        if (t < start) {
          // 进场: 向上错位滑入
          const progress = Easing.easeOutCubic((t - windowStart) / leadIn);
          y = Easing.lerp(35, 0, progress);
          opacity = Easing.lerp(0.0, 0.9, progress);
          scale = Easing.lerp(0.92, 1.0, progress);
          fontWeight = 400;
        } else if (t <= end) {
          // 演唱中活跃期: 字重暴击与微幅呼吸
          const activeProgress = (t - start) / dur;
          fontWeight = emphasis > 0.75 ? 900 : 700;
          scale = 1.0 + Math.sin(activeProgress * Math.PI) * (0.04 * emphasis);
          y = 0;
          opacity = 1.0;
        } else {
          // 退场: 被后词向上推挤出画
          const exitProgress = Easing.easeInOutCubic((t - end) / leadOut);
          y = Easing.lerp(0, -38, exitProgress);
          opacity = Easing.lerp(1.0, 0.0, exitProgress);
          scale = Easing.lerp(1.0, 1.06, exitProgress);
          fontWeight = 600;
        }

        const baseColor = emphasis > 0.8 ? '#FFFFFF' : '#E8EEF5';

        return {
          visible: true,
          text: cue.text,
          x: 0,
          y: y,
          scale: scale,
          rotation: 0,
          opacity: opacity,
          blur: 0,
          fontWeight: fontWeight,
          color: baseColor,
          backgroundColor: 'transparent',
          textStroke: 'none',
          letterSpacing: '-0.02em',
          textShadow: '0 4px 24px rgba(0,0,0,0.65)',
          isHero: emphasis > 0.8,
        };
      },
    },

    /**
     * 潮流街头贴纸与荧光色块 (Street Pop)
     * - 确定性微倾斜角、撞色粗黑描边、弹性砸入下坠
     */
    street_pop: {
      name: '街头潮酷贴纸 (Street Pop)',
      evaluate(cue, t, seed) {
        const start = cue.start;
        const end = cue.end;
        const dur = Math.max(0.1, end - start);
        const emphasis = cue.emphasis !== undefined ? cue.emphasis : 0.8;

        const leadIn = 0.18;
        const leadOut = 0.22;
        const windowStart = start - leadIn;
        const windowEnd = end + leadOut;

        if (t < windowStart || t > windowEnd) {
          return { visible: false };
        }

        // 确定性随机倾角与微偏移 (绝不随 Scrub 抽搐)
        const rotTarget = seededRandom(`${seed}:rot`, -5.5, 5.5);
        const offsetX = seededRandom(`${seed}:x`, -12, 12);

        let y = 0;
        let scale = 1.0;
        let opacity = 1.0;
        let rot = rotTarget;

        if (t < start) {
          // 弹性从天而降下砸
          const progress = Easing.easeOutOvershoot((t - windowStart) / leadIn, 2.0);
          y = Easing.lerp(-45, 0, progress);
          scale = Easing.lerp(1.35, 1.0, progress);
          opacity = Easing.lerp(0.0, 1.0, progress);
          rot = Easing.lerp(rotTarget * 2.2, rotTarget, progress);
        } else if (t <= end) {
          // 驻留期保持微冲劲
          y = 0;
          scale = 1.0;
          opacity = 1.0;
          rot = rotTarget;
        } else {
          // 快速收缩退场
          const exitProgress = Easing.easeOutCubic((t - end) / leadOut);
          y = Easing.lerp(0, 20, exitProgress);
          scale = Easing.lerp(1.0, 0.8, exitProgress);
          opacity = Easing.lerp(1.0, 0.0, exitProgress);
          rot = rotTarget + exitProgress * 4;
        }

        const bgCol = emphasis > 0.85 ? '#FFE600' : (emphasis > 0.7 ? '#FF2A6D' : '#05D9E8');
        const textCol = bgCol === '#FFE600' ? '#0D0E15' : '#FFFFFF';

        return {
          visible: true,
          text: cue.text,
          x: offsetX,
          y: y,
          scale: scale,
          rotation: rot,
          opacity: opacity,
          blur: 0,
          fontWeight: 900,
          color: textCol,
          backgroundColor: bgCol,
          textStroke: '1px rgba(0,0,0,0.85)',
          padding: '4px 16px',
          borderRadius: '4px',
          boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
          isHero: true,
        };
      },
    },

    /**
     * 赛博复古流光与焦平面景深 (Neon Glow)
     * - 高斯虚实景深切换、柔和光斑漫反射
     */
    neon_glow: {
      name: '复古霓虹流光 (Neon Glow)',
      evaluate(cue, t, seed) {
        const start = cue.start;
        const end = cue.end;
        const leadIn = 0.3;
        const leadOut = 0.35;
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
          opacity = Easing.lerp(0.1, 0.8, progress);
          blur = Easing.lerp(10, 0, progress);
          scale = Easing.lerp(0.9, 1.0, progress);
        } else if (t <= end) {
          opacity = 1.0;
          blur = 0;
          scale = 1.02;
        } else {
          const exitProgress = Easing.easeInOutCubic((t - end) / leadOut);
          opacity = Easing.lerp(1.0, 0.0, exitProgress);
          blur = Easing.lerp(0, 12, exitProgress);
          scale = Easing.lerp(1.02, 1.1, exitProgress);
        }

        return {
          visible: true,
          text: cue.text,
          x: 0,
          y: 0,
          scale: scale,
          rotation: 0,
          opacity: opacity,
          blur: blur,
          fontWeight: 700,
          color: '#E0F7FA',
          backgroundColor: 'transparent',
          textShadow: '0 0 12px #00E5FF, 0 0 32px #00B0FF, 0 0 48px #2979FF',
          letterSpacing: '0.04em',
          isHero: true,
        };
      },
    },
  };

  // ---------------------------------------------------------------------------
  // 4. DOM 高保真视口渲染器 (DOM Preview Renderer)
  // ---------------------------------------------------------------------------
  class DOMRenderer {
    constructor(containerElement) {
      this.container = containerElement;
      this.elementPool = new Map(); // cue_id -> HTMLElement
      this.initContainer();
    }

    initContainer() {
      if (!this.container) return;
      this.container.style.position = 'absolute';
      this.container.style.inset = '0';
      this.container.style.pointerEvents = 'none';
      this.container.style.display = 'flex';
      this.container.style.alignItems = 'center';
      this.container.style.justifyContent = 'center';
      this.container.style.overflow = 'hidden';
      this.container.style.zIndex = '30';
    }

    renderCue(cue, state) {
      if (!this.container) return;
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
        this.container.appendChild(el);
        this.elementPool.set(cueId, el);
      }

      el.textContent = state.text;
      el.style.display = 'block';

      // 视口响应式大字号
      el.style.fontSize = state.isHero
        ? 'clamp(38px, 6.5vw, 92px)'
        : 'clamp(28px, 4.5vw, 68px)';
      el.style.fontWeight = String(state.fontWeight || 700);
      el.style.color = state.color || '#FFFFFF';
      el.style.letterSpacing = state.letterSpacing || 'normal';
      el.style.opacity = String(state.opacity);
      el.style.filter = state.blur > 0 ? `blur(${state.blur}px)` : 'none';
      el.style.textShadow = state.textShadow || 'none';

      // 背景与边框
      if (state.backgroundColor && state.backgroundColor !== 'transparent') {
        el.style.backgroundColor = state.backgroundColor;
        el.style.padding = state.padding || '6px 18px';
        el.style.borderRadius = state.borderRadius || '6px';
        el.style.boxShadow = state.boxShadow || 'none';
        el.style.webkitTextStroke = state.textStroke || 'none';
      } else {
        el.style.backgroundColor = 'transparent';
        el.style.padding = '0';
        el.style.boxShadow = 'none';
        el.style.webkitTextStroke = 'none';
      }

      // 确定性几何变换矩阵
      const transform = `translate3d(${state.x}px, ${state.y}px, 0) scale(${state.scale}) rotate(${state.rotation}deg)`;
      el.style.transform = transform;
    }

    clear() {
      this.elementPool.forEach((el) => {
        el.style.display = 'none';
      });
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
      this.preset = options.preset || 'swiss_minimal';
      this.enabled = options.enabled !== undefined ? options.enabled : true;
      this.dsl = null;
      this.scenes = [];
      this.renderer = null;

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

    setTimeline(dsl) {
      if (!dsl) {
        this.dsl = null;
        this.scenes = [];
        if (this.renderer) this.renderer.clear();
        return;
      }
      this.dsl = dsl;
      this.scenes = dsl.scenes || [];
      if (this.renderer) this.renderer.clear();
    }

    setPreset(presetName) {
      if (Presets[presetName]) {
        this.preset = presetName;
      } else {
        console.warn(`[DeterministicMotionRuntime] 未知预设 ${presetName}, 回退到 swiss_minimal`);
        this.preset = 'swiss_minimal';
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
     * 核心纯时间函数入口: 无论何时调用 renderAt(t)，结果绝对恒定
     */
    renderAt(t) {
      if (!this.enabled || !this.renderer || !this.scenes || this.scenes.length === 0) {
        return;
      }

      const currentTime = Math.max(0, Number(t) || 0);
      const activePreset = Presets[this.preset] || Presets.swiss_minimal;

      // 寻址包含当前时间的场景 (支持转场前后适度重叠)
      for (let i = 0; i < this.scenes.length; i++) {
        const scene = this.scenes[i];
        if (currentTime >= scene.start - 0.5 && currentTime <= scene.end + 0.5) {
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
                const motionState = activePreset.evaluate(cue, currentTime, cueSeed);
                // 渲染器绘制
                this.renderer.renderCue(cue, motionState);
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
