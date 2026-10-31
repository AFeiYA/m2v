// Build this entry with frontend/motion's esbuild and serve it in a local HTML page.
// The page needs #sample containing a <canvas id="canvas">. Remove default body margin.
// Capture the top-left 720x1280 (apple/poster) or 1280x720 (karaoke) browser region.
// Sample words/timestamps are synthetic; these frames do not demonstrate alignment accuracy.
import {RemotionPreview} from '../../../../frontend/motion/src/remotion-preview';
import {demoScene} from '../../../../frontend/motion/src/marketing-demo';

const selected = new URLSearchParams(location.search).get('mode') || 'apple';
if (!['apple', 'poster', 'karaoke'].includes(selected)) throw new Error('Unknown demo mode');
const scene = demoScene(selected as 'apple' | 'poster' | 'karaoke');
scene.project.artist = 'Fovea Studio';
if (scene.project.song_identity) scene.project.song_identity.artist = 'Fovea Studio';
const host = document.getElementById('sample')!;
host.style.width = `${scene.width}px`;
host.style.height = `${scene.height}px`;
const engine = new RemotionPreview(
  document.getElementById('canvas') as HTMLCanvasElement,
  scene.project, scene.options, scene.width, scene.height,
  error => { document.body.dataset.error = error.message; },
);
engine.renderAt(selected === 'poster' ? 4.2 : 2.4);
