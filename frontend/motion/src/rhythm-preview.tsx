import React, { createRef } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Player, type PlayerRef } from '@remotion/player';
import { RhythmVideo } from './rhythm-video';
import type { Project, Options } from './model';
import type { RhythmSettings } from './rhythm-model';
/** Loaded only by Rhythm Studio, keeping Three.js out of the lyric editor bundle. */
export class RhythmPreview {
    private root: Root;
    private host: HTMLDivElement;
    private ref = createRef<PlayerRef>();
    private latest = 0;
    private raf = 0;
    constructor(canvas: HTMLCanvasElement, project: Project, options: Options, width: number, height: number, rhythm: RhythmSettings, time = 0) {
        this.latest = Math.max(0, Math.floor(time * 30));
        this.host = document.createElement('div');
        this.host.style.cssText = 'position:absolute;inset:0;width:100%;height:100%';
        canvas.hidden = true;
        canvas.parentElement!.append(this.host);
        this.root = createRoot(this.host);
        this.root.render(<Player ref={this.ref} component={RhythmVideo} inputProps={{ project, options, rhythm }} durationInFrames={Math.max(1, Math.ceil(project.duration * 30))} compositionWidth={width} compositionHeight={height} fps={30} initialFrame={this.latest} controls={false} clickToPlay={false} spaceKeyToPlayOrPause={false} style={{ width: '100%', height: '100%' }} errorFallback={({ error }) => <div role="alert" style={{ padding: 30, color: '#fca5a5' }}>3D 预览不可用：{error.message}。请检查浏览器 WebGL2 支持。</div>}/>);
        const ready = () => { if (this.ref.current)
            this.ref.current.seekTo(this.latest);
        else
            this.raf = requestAnimationFrame(ready); };
        this.raf = requestAnimationFrame(ready);
    }
    renderAt(t: number) { const frame = Math.max(0, Math.floor(t * 30)); if (frame !== this.latest || !this.ref.current) {
        this.latest = frame;
        this.ref.current?.seekTo(frame);
    } }
    dispose() { cancelAnimationFrame(this.raf); this.root.unmount(); this.host.remove(); }
}
