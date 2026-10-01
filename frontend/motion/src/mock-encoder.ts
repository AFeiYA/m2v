// Mock audio encoders for headless video rendering.
// Remotion renders video frames in Chromium, while final audio muxing is handled by native FFmpeg.
// Stubbing these avoids bundling heavy WebAssembly binaries that Hugging Face Git rejects.
export const registerAacEncoder = (): void => {};
export const registerFlacEncoder = (): void => {};
export const registerMp3Encoder = (): void => {};
