import * as THREE from 'three';
import { notePose, rhythmState, seeded, type RhythmChart, type RhythmSettings } from './rhythm-model';
/** No running clock or physics accumulation: every frame is a function of song time. */
export class RhythmScene {
    private renderer: THREE.WebGLRenderer;
    private scene = new THREE.Scene();
    private camera: THREE.PerspectiveCamera;
    private notes: THREE.Mesh[] = [];
    private towers: THREE.InstancedMesh;
    private floor: THREE.Mesh;
    private ring: THREE.Mesh;
    private hitMaterial: THREE.MeshBasicMaterial;
    private accent: THREE.Color;
    constructor(canvas: HTMLCanvasElement, width: number, height: number, private chart: RhythmChart, private settings: RhythmSettings) {
        this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, preserveDrawingBuffer: true });
        this.renderer.setPixelRatio(1);
        this.renderer.setSize(width, height, false);
        this.renderer.outputColorSpace = THREE.SRGBColorSpace;
        this.accent = new THREE.Color(settings.palette === 'violet' ? '#be83ff' : '#64f7eb');
        this.scene.background = new THREE.Color('#070d17');
        this.scene.fog = new THREE.Fog('#070d17', 24, 80);
        this.camera = new THREE.PerspectiveCamera(height > width ? 64 : 52, width / height, .1, 160);
        this.camera.position.set(0, 6.7, 10.5);
        this.camera.lookAt(0, 0, -5);
        const floorMat = new THREE.MeshBasicMaterial({ color: '#111c2b' });
        this.floor = new THREE.Mesh(new THREE.PlaneGeometry(10, 140), floorMat);
        this.floor.rotation.x = -Math.PI / 2;
        this.floor.position.set(0, -.05, -55);
        this.scene.add(this.floor);
        const vertices: number[] = [];
        for (const x of [-3.45, -1.15, 1.15, 3.45])
            vertices.push(x, 0, -100, x, 0, 5);
        for (let z = -100; z <= 5; z += 4)
            vertices.push(-3.45, 0, z, 3.45, 0, z);
        const grid = new THREE.LineSegments(new THREE.BufferGeometry().setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3)), new THREE.LineBasicMaterial({ color: '#2d485b', transparent: true, opacity: .65 }));
        this.scene.add(grid);
        const hit = new THREE.Mesh(new THREE.BoxGeometry(7, .05, .12), new THREE.MeshBasicMaterial({ color: this.accent }));
        hit.position.set(0, .03, 0);
        this.scene.add(hit);
        this.hitMaterial = new THREE.MeshBasicMaterial({ color: this.accent, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false });
        this.ring = new THREE.Mesh(new THREE.RingGeometry(.7, .76, 48), this.hitMaterial);
        this.ring.rotation.x = -Math.PI / 2;
        this.ring.position.set(0, .08, 0);
        this.scene.add(this.ring);
        const towerMat = new THREE.MeshBasicMaterial({ color: '#182c42', wireframe: true });
        this.towers = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), towerMat, 64);
        this.towers.frustumCulled = false;
        this.scene.add(this.towers);
        const geometry = new THREE.BoxGeometry(1.7, .22, .7), material = new THREE.MeshBasicMaterial({ color: this.accent });
        for (let i = 0; i < 64; i++) {
            const mesh = new THREE.Mesh(geometry, material);
            mesh.visible = false;
            this.notes.push(mesh);
            this.scene.add(mesh);
        }
    }
    renderAt(t: number) {
        const state = rhythmState(this.chart, t);
        let cursor = 0;
        // Sorted chart: inspect only the local window, never all note meshes at once.
        for (let i = Math.max(0, state.combo - 1); i < this.chart.notes.length && cursor < this.notes.length; i++) {
            const note = this.chart.notes[i];
            if (note.time - t > this.settings.approach)
                break;
            const pose = notePose(note, t, this.settings.approach);
            if (!pose.visible)
                continue;
            const mesh = this.notes[cursor++];
            mesh.visible = true;
            mesh.position.set(pose.x, .25, pose.z);
            mesh.scale.set(1, 1 + note.strength * .3, 1);
        }
        for (; cursor < this.notes.length; cursor++)
            this.notes[cursor].visible = false;
        const matrix = new THREE.Matrix4(), position = new THREE.Vector3(), scale = new THREE.Vector3(), rotation = new THREE.Quaternion();
        for (let i = 0; i < 64; i++) {
            const height = 2 + seeded(i + 90, this.settings.seed) * 12, z = -((i >> 1) * 4.8 - (t * 6) % 4.8);
            position.set((i % 2 ? 1 : -1) * (6 + seeded(i + 2, this.settings.seed) * 5), height / 2, z);
            scale.set(1.1, height, 1.1);
            matrix.compose(position, rotation, scale);
            this.towers.setMatrixAt(i, matrix);
        }
        this.towers.instanceMatrix.needsUpdate = true;
        this.hitMaterial.opacity = state.flash * .75;
        this.ring.position.x = state.last ? (state.last.lane - 1) * 2.3 : 0;
        this.ring.scale.setScalar(1 + (1 - state.flash) * 1.8);
        this.renderer.render(this.scene, this.camera);
    }
    dispose() { const geometries = new Set<THREE.BufferGeometry>(), materials = new Set<THREE.Material>(); this.scene.traverse(obj => { const mesh = obj as THREE.Mesh; if (mesh.geometry)
        geometries.add(mesh.geometry); if (mesh.material)
        for (const m of Array.isArray(mesh.material) ? mesh.material : [mesh.material])
            materials.add(m); }); geometries.forEach(g => g.dispose()); materials.forEach(m => m.dispose()); this.renderer.dispose(); this.renderer.forceContextLoss(); }
}
