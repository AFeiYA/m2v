export function hexToRgba(hex: string, alpha: number): string {
  const clean = hex.replace('#', '');
  if (/^[0-9a-fA-F]{3}$/.test(clean)) {
    const r = parseInt(clean[0] + clean[0], 16);
    const g = parseInt(clean[1] + clean[1], 16);
    const b = parseInt(clean[2] + clean[2], 16);
    return `rgba(${r},${g},${b},${alpha})`;
  }
  if (/^[0-9a-fA-F]{6}$/.test(clean)) {
    const r = parseInt(clean.slice(0, 2), 16);
    const g = parseInt(clean.slice(2, 4), 16);
    const b = parseInt(clean.slice(4, 6), 16);
    return `rgba(${r},${g},${b},${alpha})`;
  }
  return `rgba(255,255,255,${alpha})`;
}

export type AmbientParticle = {
  x: number;
  y: number;
  radius: number;
  alpha: number;
  color: string;
};

function pseudo(seed: number): number {
  const x = Math.sin(seed * 12.9898 + 78.233) * 43758.5453;
  return x - Math.floor(x);
}

/**
 * 确定性悬浮微光粒子计算 (48 颗星尘 / 浮尘粒子)
 * 纯数学函数计算，保证在每一帧 t 上 100% 幂等可重现，无随机状态漂移。
 * speedScale 默认 0.5，带来更空灵、轻柔、不抢焦点的慢速悬浮感（支持 0.05 ~ 3.0 动态微调）。
 */
export function computeParticles(
  W: number,
  H: number,
  t: number,
  count = 48,
  pulse = 1,
  speedScale = 0.5,
  darken = 0.4
): AmbientParticle[] {
  const particles: AmbientParticle[] = [];
  const beatKick = Math.max(0, pulse - 1);
  const safeSpeed = Math.max(0.01, speedScale);
  const safeDarken = Math.max(0, Math.min(1, darken));

  for (let i = 0; i < count; i++) {
    const seedX = pseudo(i * 1.618);
    const seedY = pseudo(i * 2.718);
    const speedY = (0.007 + pseudo(i * 3.141) * 0.013) * safeSpeed;
    const wobbleSpeed = (0.22 + pseudo(i * 4.123) * 0.38) * Math.sqrt(safeSpeed);
    const wobbleAmp = 0.008 + pseudo(i * 5.342) * 0.014;
    const phase = pseudo(i * 6.789) * Math.PI * 2;
    const baseRadius = 0.9 + pseudo(i * 7.432) * 2.4;
    const baseAlpha = (0.16 + pseudo(i * 8.912) * 0.36) * (1.1 - safeDarken * 0.3);

    // 垂直方向平滑循环上升
    const normY = ((seedY - t * speedY) % 1.0 + 1.0) % 1.0;
    // 水平方向微幅正弦晃动
    const normX = seedX + Math.sin(t * wobbleSpeed + phase) * wobbleAmp;

    // 呼吸忽明忽暗闪烁
    const twinkleFreq = 0.8 + 0.6 * safeSpeed;
    let alpha = baseAlpha * (0.65 + 0.35 * Math.sin(t * twinkleFreq + phase));
    // 上下边缘柔和淡入淡出，消除跳变感
    const edgeFade = Math.sin(normY * Math.PI);
    alpha *= edgeFade;

    // 音频节拍瞬态微脉冲
    if (beatKick > 0.001) {
      alpha = Math.min(0.9, alpha * (1 + beatKick * 2.2));
    }

    const radius = baseRadius * (1 + beatKick * 0.4);

    particles.push({
      x: normX * W,
      y: normY * H,
      radius: Number(radius.toFixed(2)),
      alpha: Number(Math.max(0, Math.min(1, alpha)).toFixed(3)),
      color: i % 3 === 0 ? '#fffdf0' : '#ffffff',
    });
  }

  return particles;
}

/**
 * 极光流体光球位置计算 (双光球慢速旋转与游走)
 */
export function computeAmbientOrbs(W: number, H: number, t: number, accent: string, speedScale = 0.5, darken = 0.4) {
  const safeSpeed = Math.max(0.01, speedScale);
  const safeDarken = Math.max(0, Math.min(1, darken));
  const cx1 = W * (0.35 + 0.16 * Math.sin(t * 0.09 * safeSpeed));
  const cy1 = H * (0.36 + 0.14 * Math.cos(t * 0.07 * safeSpeed));
  const r1 = Math.max(W, H) * 0.65;

  const cx2 = W * (0.66 + 0.15 * Math.cos(t * 0.08 * safeSpeed + 1.2));
  const cy2 = H * (0.64 + 0.16 * Math.sin(t * 0.10 * safeSpeed + 0.8));
  const r2 = Math.max(W, H) * 0.72;

  const alpha1 = Number((0.13 * (1.1 - safeDarken * 0.28)).toFixed(3));
  const alpha2 = Number((0.08 * (1.1 - safeDarken * 0.28)).toFixed(3));

  return {
    orb1: { cx: cx1, cy: cy1, r: r1, color: hexToRgba(accent, alpha1) },
    orb2: { cx: cx2, cy: cy2, r: r2, color: hexToRgba(accent, alpha2) },
  };
}

/**
 * 在已有底色或封面上叠加流体极光光斑、悬浮粒子与暗角
 */
export function paintAmbientAuraAndParticles(
  c: CanvasRenderingContext2D,
  W: number,
  H: number,
  t: number,
  accent: string,
  pulse = 1,
  speedScale = 0.5,
  darken = 0.4
) {
  c.save();
  const safeDarken = Math.max(0, Math.min(1, darken));
  // 1. 流体极光双光斑柔和漫反射
  const { orb1, orb2 } = computeAmbientOrbs(W, H, t, accent, speedScale, safeDarken);

  const g1 = c.createRadialGradient(orb1.cx, orb1.cy, 0, orb1.cx, orb1.cy, orb1.r);
  g1.addColorStop(0, orb1.color);
  g1.addColorStop(0.5, hexToRgba(accent, 0.04));
  g1.addColorStop(1, 'transparent');
  c.fillStyle = g1;
  c.fillRect(0, 0, W, H);

  const g2 = c.createRadialGradient(orb2.cx, orb2.cy, 0, orb2.cx, orb2.cy, orb2.r);
  g2.addColorStop(0, orb2.color);
  g2.addColorStop(0.6, hexToRgba(accent, 0.02));
  g2.addColorStop(1, 'transparent');
  c.fillStyle = g2;
  c.fillRect(0, 0, W, H);

  // 2. 悬浮微光微尘粒子
  const particles = computeParticles(W, H, t, 48, pulse, speedScale, safeDarken);
  for (const p of particles) {
    if (p.alpha <= 0.01) continue;
    c.save();
    c.globalAlpha = p.alpha;
    c.fillStyle = p.color;
    c.beginPath();
    c.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
    c.fill();
    c.restore();
  }

  // 3. 四周深色暗角压暗 (Vignette)，根据 darken 参数动态调节明暗与对比度
  const minDim = Math.min(W, H);
  const maxDim = Math.max(W, H);
  const vig = c.createRadialGradient(W / 2, H / 2, minDim * 0.25, W / 2, H / 2, maxDim * 0.75);
  const innerA = Math.max(0, (safeDarken - 0.35) * 0.4);
  const midA = 0.08 + safeDarken * 0.32;
  const outerA = 0.32 + safeDarken * 0.58;
  vig.addColorStop(0, `rgba(0, 0, 0, ${innerA.toFixed(3)})`);
  vig.addColorStop(0.5, `rgba(0, 0, 0, ${midA.toFixed(3)})`);
  vig.addColorStop(1, `rgba(0, 0, 0, ${outerA.toFixed(3)})`);
  c.fillStyle = vig;
  c.fillRect(0, 0, W, H);

  c.restore();
}

/**
 * 完整绘制：底层纯色 + 流体极光 + 悬浮微尘粒子 + 四周暗角
 */
export function paintAmbientBackground(
  c: CanvasRenderingContext2D,
  W: number,
  H: number,
  t: number,
  background: string,
  accent: string,
  pulse = 1,
  speedScale = 0.5,
  darken = 0.4
) {
  c.save();
  c.fillStyle = background;
  c.fillRect(0, 0, W, H);
  paintAmbientAuraAndParticles(c, W, H, t, accent, pulse, speedScale, darken);
  c.restore();
}
