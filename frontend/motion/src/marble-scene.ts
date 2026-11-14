import * as THREE from 'three';
import {
  evaluateMarblePose,
  seeded,
  type MarbleHitNode,
  type MarbleSettings,
  type MarbleTrack,
} from './marble-model';

type ThemePalette = {
  bg: string;
  fog: string;
  primaryMarble: string;
  secondaryMarble: string;
  barLow: string;
  barHigh: string;
  hitGlow: string;
  rail: string;
  ambient: string;
};

const THEMES: Record<MarbleSettings['theme'], ThemePalette> = {
  amber: {
    bg: '#09070c',
    fog: '#09070c',
    primaryMarble: '#ffd166',
    secondaryMarble: '#5eead4',
    barLow: '#f97316',
    barHigh: '#fde047',
    hitGlow: '#fffbeb',
    rail: '#3f2e26',
    ambient: '#3b2b20',
  },
  neon: {
    bg: '#060b16',
    fog: '#060b16',
    primaryMarble: '#64f7eb',
    secondaryMarble: '#f472b6',
    barLow: '#818cf8',
    barHigh: '#2dd4bf',
    hitGlow: '#f0fdfa',
    rail: '#1e3a5f',
    ambient: '#172554',
  },
  christmas: {
    bg: '#160406',
    fog: '#160406',
    primaryMarble: '#fcd34d',
    secondaryMarble: '#e2e8f0',
    barLow: '#dc2626',
    barHigh: '#10b981',
    hitGlow: '#fef08a',
    rail: '#4c1d1d',
    ambient: '#3f1215',
  },
};

const BAR_POOL_SIZE = 96;
const TRAIL_LEN = 12;
const SPARK_POOL_SIZE = 96;
const RING_POOL_SIZE = 8;

function lowerBoundTime(nodes: MarbleHitNode[], t: number): number {
  let lo = 0;
  let hi = nodes.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (nodes[mid].time < t) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** Deterministic Three.js 3D Marble Music stage: every frame is a pure function of song time t. */
export class MarbleScene {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera: THREE.PerspectiveCamera;
  private palette: ThemePalette;

  private primaryMarble: THREE.Mesh;
  private secondaryMarble: THREE.Mesh;
  private primaryLight: THREE.PointLight;
  private primaryTrail: THREE.Mesh[] = [];
  private secondaryTrail: THREE.Mesh[] = [];

  private barMeshes: THREE.Mesh[] = [];
  private barMaterials: THREE.MeshStandardMaterial[] = [];
  private ringMeshes: THREE.Mesh[] = [];
  private ringMaterials: THREE.MeshBasicMaterial[] = [];
  private sparks: THREE.InstancedMesh;
  private pillars: THREE.InstancedMesh;

  private barColorLow: THREE.Color;
  private barColorHigh: THREE.Color;
  private hitGlowColor: THREE.Color;

  constructor(
    canvas: HTMLCanvasElement,
    width: number,
    height: number,
    private track: MarbleTrack,
    private settings: MarbleSettings
  ) {
    this.palette = THEMES[settings.theme] || THEMES.amber;
    this.barColorLow = new THREE.Color(this.palette.barLow);
    this.barColorHigh = new THREE.Color(this.palette.barHigh);
    this.hitGlowColor = new THREE.Color(this.palette.hitGlow);

    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: false,
      preserveDrawingBuffer: true,
    });
    this.renderer.setPixelRatio(1);
    this.renderer.setSize(width, height, false);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;

    this.scene.background = new THREE.Color(this.palette.bg);
    this.scene.fog = new THREE.Fog(this.palette.fog, 22, 92);

    this.camera = new THREE.PerspectiveCamera(height > width ? 62 : 50, width / height, 0.1, 180);

    const hemi = new THREE.HemisphereLight('#ffffff', this.palette.ambient, 0.9);
    this.scene.add(hemi);
    const dir = new THREE.DirectionalLight('#ffffff', 1.15);
    dir.position.set(12, 24, 14);
    this.scene.add(dir);

    this.primaryLight = new THREE.PointLight(this.palette.primaryMarble, 3.2, 22, 1.5);
    this.scene.add(this.primaryLight);

    // Primary & secondary marbles
    const marbleGeo = new THREE.SphereGeometry(0.42, 28, 28);
    this.primaryMarble = new THREE.Mesh(
      marbleGeo,
      new THREE.MeshStandardMaterial({
        color: this.palette.primaryMarble,
        emissive: this.palette.primaryMarble,
        emissiveIntensity: 0.45,
        roughness: 0.18,
        metalness: 0.65,
      })
    );
    this.scene.add(this.primaryMarble);

    this.secondaryMarble = new THREE.Mesh(
      marbleGeo,
      new THREE.MeshStandardMaterial({
        color: this.palette.secondaryMarble,
        emissive: this.palette.secondaryMarble,
        emissiveIntensity: 0.4,
        roughness: 0.22,
        metalness: 0.6,
      })
    );
    this.scene.add(this.secondaryMarble);

    // Trails
    const trailGeo = new THREE.SphereGeometry(0.24, 12, 12);
    for (let i = 0; i < TRAIL_LEN; i++) {
      const ratio = 1 - i / TRAIL_LEN;
      const pMat = new THREE.MeshBasicMaterial({
        color: this.palette.primaryMarble,
        transparent: true,
        opacity: ratio * 0.42,
        depthWrite: false,
      });
      const pMesh = new THREE.Mesh(trailGeo, pMat);
      pMesh.scale.setScalar(ratio * 0.85);
      pMesh.visible = false;
      this.primaryTrail.push(pMesh);
      this.scene.add(pMesh);

      const sMat = new THREE.MeshBasicMaterial({
        color: this.palette.secondaryMarble,
        transparent: true,
        opacity: ratio * 0.35,
        depthWrite: false,
      });
      const sMesh = new THREE.Mesh(trailGeo, sMat);
      sMesh.scale.setScalar(ratio * 0.78);
      sMesh.visible = false;
      this.secondaryTrail.push(sMesh);
      this.scene.add(sMesh);
    }

    // Xylophone / musical bars pool
    const barGeo = new THREE.BoxGeometry(1, 0.28, 0.78);
    for (let i = 0; i < BAR_POOL_SIZE; i++) {
      const mat = new THREE.MeshStandardMaterial({
        color: this.palette.barLow,
        emissive: this.palette.barLow,
        emissiveIntensity: 0.18,
        roughness: 0.3,
        metalness: 0.35,
      });
      const mesh = new THREE.Mesh(barGeo, mat);
      mesh.visible = false;
      this.barMeshes.push(mesh);
      this.barMaterials.push(mat);
      this.scene.add(mesh);
    }

    // Impact rings pool
    const ringGeo = new THREE.RingGeometry(0.42, 0.58, 32);
    for (let i = 0; i < RING_POOL_SIZE; i++) {
      const rMat = new THREE.MeshBasicMaterial({
        color: this.palette.hitGlow,
        transparent: true,
        opacity: 0,
        side: THREE.DoubleSide,
        depthWrite: false,
      });
      const rMesh = new THREE.Mesh(ringGeo, rMat);
      rMesh.rotation.x = -Math.PI / 2;
      rMesh.visible = false;
      this.ringMeshes.push(rMesh);
      this.ringMaterials.push(rMat);
      this.scene.add(rMesh);
    }

    // Sparks instanced pool
    const sparkGeo = new THREE.OctahedronGeometry(0.11, 0);
    const sparkMat = new THREE.MeshBasicMaterial({
      color: this.palette.hitGlow,
      transparent: true,
      opacity: 0.9,
    });
    this.sparks = new THREE.InstancedMesh(sparkGeo, sparkMat, SPARK_POOL_SIZE);
    this.sparks.frustumCulled = false;
    this.scene.add(this.sparks);

    // Side architectural rails/pillars
    const pillarGeo = new THREE.BoxGeometry(0.45, 1, 0.45);
    const pillarMat = new THREE.MeshStandardMaterial({
      color: this.palette.rail,
      roughness: 0.65,
      metalness: 0.2,
    });
    this.pillars = new THREE.InstancedMesh(pillarGeo, pillarMat, 48);
    this.pillars.frustumCulled = false;
    this.scene.add(this.pillars);
  }

  renderAt(t: number) {
    const primaryPose = evaluateMarblePose(this.track.primary, t);
    this.primaryMarble.visible = primaryPose.active;
    this.primaryMarble.position.set(primaryPose.x, primaryPose.y + 0.42, primaryPose.z);
    this.primaryMarble.rotation.x = -primaryPose.spin;
    this.primaryLight.position.set(primaryPose.x, primaryPose.y + 2.2, primaryPose.z);

    for (let i = 0; i < TRAIL_LEN; i++) {
      const sampleT = t - (i + 1) * 0.022;
      if (sampleT < 0 || !primaryPose.active) {
        this.primaryTrail[i].visible = false;
      } else {
        const tp = evaluateMarblePose(this.track.primary, sampleT);
        this.primaryTrail[i].visible = true;
        this.primaryTrail[i].position.set(tp.x, tp.y + 0.42, tp.z);
      }
    }

    const hasSecondary = this.settings.tracks === 'dual' && this.track.secondary.length > 0;
    if (hasSecondary) {
      const secPose = evaluateMarblePose(this.track.secondary, t);
      this.secondaryMarble.visible = secPose.active;
      this.secondaryMarble.position.set(secPose.x, secPose.y + 0.36, secPose.z);
      this.secondaryMarble.scale.setScalar(0.84);
      this.secondaryMarble.rotation.x = -secPose.spin;
      for (let i = 0; i < TRAIL_LEN; i++) {
        const sampleT = t - (i + 1) * 0.022;
        if (sampleT < 0 || !secPose.active) {
          this.secondaryTrail[i].visible = false;
        } else {
          const tp = evaluateMarblePose(this.track.secondary, sampleT);
          this.secondaryTrail[i].visible = true;
          this.secondaryTrail[i].position.set(tp.x, tp.y + 0.36, tp.z);
        }
      }
    } else {
      this.secondaryMarble.visible = false;
      for (const m of this.secondaryTrail) m.visible = false;
    }

    // Update visible musical bars window [t - 1.8s, t + 9.0s]
    const all = this.track.allNodes;
    const startIdx = lowerBoundTime(all, t - 1.8);
    let barCursor = 0;
    let ringCursor = 0;
    let sparkCursor = 0;

    const tmpColor = new THREE.Color();
    const dummyMatrix = new THREE.Matrix4();
    const dummyPos = new THREE.Vector3();
    const dummyQuat = new THREE.Quaternion();
    const dummyScale = new THREE.Vector3();

    for (let i = startIdx; i < all.length && barCursor < BAR_POOL_SIZE; i++) {
      const node = all[i];
      if (node.time - t > 9.5) break;

      const mesh = this.barMeshes[barCursor];
      const mat = this.barMaterials[barCursor];
      barCursor++;

      const age = t - node.time;
      const hitStrength = age >= 0 && age < 0.38 ? Math.exp(-age * 8.5) : 0;
      const recoil = age >= 0 && age < 0.35 ? -0.26 * Math.sin((age / 0.35) * Math.PI) : 0;

      mesh.visible = true;
      mesh.position.set(node.x, node.y - 0.14 + recoil, node.z);
      mesh.scale.set(node.width, 1, 1);

      tmpColor.copy(this.barColorLow).lerp(this.barColorHigh, node.colorRatio);
      if (hitStrength > 0.01) {
        tmpColor.lerp(this.hitGlowColor, hitStrength * 0.85);
      }
      mat.color.copy(tmpColor);
      mat.emissive.copy(tmpColor);
      mat.emissiveIntensity = 0.22 + hitStrength * 1.45;

      // Recent hit shockwave ring + deterministic sparks
      if (age >= 0 && age < 0.48) {
        if (ringCursor < RING_POOL_SIZE) {
          const rMesh = this.ringMeshes[ringCursor];
          const rMat = this.ringMaterials[ringCursor];
          ringCursor++;
          const k = age / 0.48;
          rMesh.visible = true;
          rMesh.position.set(node.x, node.y + 0.04, node.z);
          rMesh.scale.setScalar(1 + k * 2.6);
          rMat.opacity = (1 - k) * 0.85;
        }
        for (let s = 0; s < 6 && sparkCursor < SPARK_POOL_SIZE; s++) {
          const angle = seeded(node.index * 17 + s, this.settings.seed) * Math.PI * 2;
          const speed = 2.2 + seeded(node.index * 31 + s, this.settings.seed) * 2.8;
          const vy = 3.2 + seeded(node.index * 47 + s, this.settings.seed) * 2.4;
          const sx = node.x + Math.cos(angle) * speed * age;
          const sz = node.z + Math.sin(angle) * speed * age;
          const sy = node.y + 0.15 + vy * age - 4.9 * age * age;
          const fade = Math.max(0.01, 1 - age / 0.48);
          dummyPos.set(sx, sy, sz);
          dummyScale.setScalar(fade * 1.1);
          dummyMatrix.compose(dummyPos, dummyQuat, dummyScale);
          this.sparks.setMatrixAt(sparkCursor++, dummyMatrix);
        }
      }
    }

    for (; barCursor < BAR_POOL_SIZE; barCursor++) {
      this.barMeshes[barCursor].visible = false;
    }
    for (; ringCursor < RING_POOL_SIZE; ringCursor++) {
      this.ringMeshes[ringCursor].visible = false;
    }
    dummyScale.setScalar(0);
    dummyPos.set(0, -999, 0);
    dummyMatrix.compose(dummyPos, dummyQuat, dummyScale);
    for (; sparkCursor < SPARK_POOL_SIZE; sparkCursor++) {
      this.sparks.setMatrixAt(sparkCursor, dummyMatrix);
    }
    this.sparks.instanceMatrix.needsUpdate = true;

    // Update flanking architectural pillars following the descending course
    const baseStep = Math.floor(t / 0.8);
    for (let i = 0; i < 48; i++) {
      const stepIdx = baseStep - 4 + (i >> 1);
      const stepT = stepIdx * 0.8;
      const side = i % 2 === 0 ? -1 : 1;
      const h = 4 + seeded(stepIdx * 7 + (i % 2), this.settings.seed) * 9;
      const pz = -stepT * 7.2;
      const py = -stepT * 1.45 - h * 0.5 - 1.2;
      const px = side * (7.8 + seeded(stepIdx * 13 + side, this.settings.seed) * 3.5);
      dummyPos.set(px, py, pz);
      dummyScale.set(1, h, 1);
      dummyMatrix.compose(dummyPos, dummyQuat, dummyScale);
      this.pillars.setMatrixAt(i, dummyMatrix);
    }
    this.pillars.instanceMatrix.needsUpdate = true;

    // Camera placement
    if (this.settings.camera === 'isometric') {
      this.camera.position.set(primaryPose.x * 0.35 + 10.5, primaryPose.y + 8.8, primaryPose.z + 10.2);
      this.camera.lookAt(primaryPose.x * 0.5, primaryPose.y - 1.0, primaryPose.z - 6.5);
    } else if (this.settings.camera === 'rail') {
      this.camera.position.set(primaryPose.x * 0.72, primaryPose.y + 2.35, primaryPose.z + 5.6);
      this.camera.lookAt(primaryPose.x * 0.75, primaryPose.y - 0.5, primaryPose.z - 10.5);
    } else {
      // 'follow'
      this.camera.position.set(primaryPose.x * 0.45, primaryPose.y + 5.1, primaryPose.z + 10.8);
      this.camera.lookAt(primaryPose.x * 0.6, primaryPose.y - 0.8, primaryPose.z - 8.5);
    }

    this.renderer.render(this.scene, this.camera);
  }

  dispose() {
    const geometries = new Set<THREE.BufferGeometry>();
    const materials = new Set<THREE.Material>();
    this.scene.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      if (mesh.geometry) geometries.add(mesh.geometry);
      if (mesh.material) {
        for (const m of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
          materials.add(m);
        }
      }
    });
    geometries.forEach((g) => g.dispose());
    materials.forEach((m) => m.dispose());
    this.renderer.dispose();
    this.renderer.forceContextLoss();
  }
}
