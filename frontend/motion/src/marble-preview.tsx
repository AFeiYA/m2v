import React, { createRef } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { Player, type PlayerRef } from '@remotion/player';
import { MarbleVideo } from './marble-video';
import type { Project, Options } from './model';
import type { MarbleNoteInput, MarbleSettings } from './marble-model';

/** Loaded only by Marble Studio, keeping Three.js out of the lyric editor bundle. */
export class MarblePreview {
  private root: Root;
  private host: HTMLDivElement;
  private ref = createRef<PlayerRef>();
  private latest = 0;
  private raf = 0;

  constructor(
    canvas: HTMLCanvasElement,
    project: Project,
    options: Options,
    width: number,
    height: number,
    marble: MarbleSettings,
    marbleNotes: MarbleNoteInput[],
    time = 0
  ) {
    this.latest = Math.max(0, Math.floor(time * 30));
    this.host = document.createElement('div');
    this.host.style.cssText = 'position:absolute;inset:0;width:100%;height:100%';
    canvas.hidden = true;
    canvas.parentElement!.append(this.host);
    this.root = createRoot(this.host);
    this.root.render(
      <Player
        ref={this.ref}
        component={MarbleVideo}
        inputProps={{ project, options, marble, marbleNotes }}
        durationInFrames={Math.max(1, Math.ceil(project.duration * 30))}
        compositionWidth={width}
        compositionHeight={height}
        fps={30}
        initialFrame={this.latest}
        controls={false}
        clickToPlay={false}
        spaceKeyToPlayOrPause={false}
        style={{ width: '100%', height: '100%' }}
        errorFallback={({ error }) => (
          <div role="alert" style={{ padding: 30, color: '#fca5a5' }}>
            3D preview unavailable: {error.message}. Check WebGL2 support in your browser.
          </div>
        )}
      />
    );
    const ready = () => {
      if (this.ref.current) this.ref.current.seekTo(this.latest);
      else this.raf = requestAnimationFrame(ready);
    };
    this.raf = requestAnimationFrame(ready);
  }

  renderAt(t: number) {
    const frame = Math.max(0, Math.floor(t * 30));
    if (frame !== this.latest || !this.ref.current) {
      this.latest = frame;
      this.ref.current?.seekTo(frame);
    }
  }

  dispose() {
    cancelAnimationFrame(this.raf);
    this.root.unmount();
    this.host.remove();
  }
}
