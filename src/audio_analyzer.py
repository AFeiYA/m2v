#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
M2V Audio Analyzer for 3D Rhythm Game
--------------------------------------
Analyzes audio files (MP3/WAV) using Librosa to extract:
1. BPM and beat timestamps.
2. Measure/bar boundaries (4/4 meter).
3. Discrete note events: Kick (low freq), Snare (mid freq), Hi-hat (high freq).
4. Continuous time-series features (RMS energy, Chroma pitch vector, Onset envelope).
5. Pre-calculated 3D track geometry (X/Y offsets) for spline generation.
"""

import os
import sys
import json
import argparse
import numpy as np
import scipy.signal

# Monkeypatch scipy.signal.hann for newer scipy versions and older librosa versions
if not hasattr(scipy.signal, "hann"):
    import scipy.signal.windows
    scipy.signal.hann = scipy.signal.windows.hann

import librosa

def parse_args():
    parser = argparse.ArgumentParser(description="M2V Audio Analyzer for Three.js 3D Game")
    parser.add_argument("--audio", required=True, help="Path to input audio file (WAV/MP3)")
    parser.add_argument("--output", required=True, help="Path to output JSON file")
    parser.add_argument("--fps", type=int, default=20, help="Features sampling rate (default: 20Hz)")
    return parser.parse_args()

def find_peaks(envelope, times, sr, hop_length, min_dist_sec=0.18, threshold_factor=1.2):
    """
    Find local peaks in an energy envelope that exceed a dynamic threshold.
    """
    mean_val = np.mean(envelope)
    std_val = np.std(envelope)
    threshold = mean_val + threshold_factor * std_val
    
    peaks = []
    min_dist_frames = int(round(min_dist_sec * sr / hop_length))
    last_peak_frame = -min_dist_frames
    
    for i in range(1, len(envelope) - 1):
        if envelope[i] > envelope[i-1] and envelope[i] > envelope[i+1]:
            if envelope[i] > threshold:
                if i - last_peak_frame >= min_dist_frames:
                    peaks.append(float(times[i]))
                    last_peak_frame = i
    return peaks

def main():
    args = parse_args()
    
    if not os.path.exists(args.audio):
        print(f"Error: Audio file not found: {args.audio}", file=sys.stderr)
        sys.exit(1)
        
    print(f"Analyzing: {args.audio}")
    
    # 1. Load Audio
    # Resample to 22050Hz for standard audio feature extraction speed
    y, sr = librosa.load(args.audio, sr=22050)
    duration = librosa.get_duration(y=y, sr=sr)
    print(f"  Duration: {duration:.2f} seconds")
    print(f"  Sample Rate: {sr} Hz")
    
    # 2. HPSS: Separate Percussive and Harmonic components
    print("  Separating percussive and harmonic stems...")
    y_harm, y_perc = librosa.effects.hpss(y)
    
    # 3. Tempo & Beat Detection
    print("  Estimating tempo and beats...")
    tempo, beat_frames = librosa.beat.beat_track(y=y_perc, sr=sr)
    bpm = float(tempo[0]) if isinstance(tempo, np.ndarray) else float(tempo)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    print(f"  Estimated BPM: {bpm:.2f}")
    print(f"  Detected Beats: {len(beat_times)}")
    
    # Group beats into 4/4 bars (every 4 beats is one bar)
    bar_lines = []
    for i in range(0, len(beat_times), 4):
        bar_lines.append(beat_times[i])
        
    # 4. Extract Kick, Snare, Hi-Hat events using spectrogram band filtering
    print("  Extracting drum track events (Kick, Snare, Hi-hat)...")
    hop_length = 512
    stft = np.abs(librosa.stft(y_perc, hop_length=hop_length))
    freqs = librosa.fft_frequencies(sr=sr)
    times = librosa.frames_to_time(np.arange(stft.shape[1]), sr=sr, hop_length=hop_length)
    
    # Filter bands
    # Kick: 20Hz - 120Hz
    kick_mask = freqs < 120
    kick_env = np.sum(stft[kick_mask, :], axis=0)
    
    # Snare: 200Hz - 1000Hz
    snare_mask = (freqs >= 200) & (freqs < 1000)
    snare_env = np.sum(stft[snare_mask, :], axis=0)
    
    # Hi-hat: 4000Hz - 8000Hz
    hat_mask = (freqs >= 4000) & (freqs < 8000)
    hat_env = np.sum(stft[hat_mask, :], axis=0)
    
    # Detect peaks
    # Hi-hats occur rapidly, so smaller min_dist
    kick_peaks = find_peaks(kick_env, times, sr, hop_length, min_dist_sec=0.22, threshold_factor=1.2)
    snare_peaks = find_peaks(snare_env, times, sr, hop_length, min_dist_sec=0.25, threshold_factor=1.3)
    hat_peaks = find_peaks(hat_env, times, sr, hop_length, min_dist_sec=0.15, threshold_factor=1.0)
    
    print(f"    Kick hits: {len(kick_peaks)}")
    print(f"    Snare hits: {len(snare_peaks)}")
    print(f"    Hi-hat hits: {len(hat_peaks)}")
    
    # Compile notes list
    notes = []
    for t in kick_peaks:
        notes.append({"time": t, "type": "kick", "lane": 1}) # Kick is center lane (1)
    for t in snare_peaks:
        # Alternating left (0) and right (2) lanes for snares to force lane shifting
        lane = 0 if len([n for n in notes if n["type"] == "snare"]) % 2 == 0 else 2
        notes.append({"time": t, "type": "snare", "lane": lane})
    for t in hat_peaks:
        # Distribute hats on lanes 0 and 2
        lane = 0 if len([n for n in notes if n["type"] == "hat"]) % 2 == 0 else 2
        notes.append({"time": t, "type": "hat", "lane": lane})
        
    # Sort notes by time
    notes = sorted(notes, key=lambda x: x["time"])
    
    # 5. Extract continuous envelopes (RMS, Chroma, Onset) at target FPS
    print(f"  Downsampling features to {args.fps}Hz...")
    rms_raw = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    chroma_raw = librosa.feature.chroma_cens(y=y_harm, sr=sr, hop_length=hop_length) # 12 x N
    onset_raw = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length)
    
    hop_sec = hop_length / sr
    fps_ratio = int(round(1.0 / (args.fps * hop_sec)))
    if fps_ratio < 1:
        fps_ratio = 1
        
    times_raw = librosa.frames_to_time(np.arange(len(rms_raw)), sr=sr, hop_length=hop_length)
    
    sampled_times = times_raw[::fps_ratio]
    sampled_rms = rms_raw[::fps_ratio]
    sampled_onset = onset_raw[::fps_ratio]
    
    sampled_chroma = []
    for col in range(0, chroma_raw.shape[1], fps_ratio):
        sampled_chroma.append(chroma_raw[:, col].tolist())
        
    # 6. Procedural 3D Track Spline Offset Pre-calculation
    # We pre-calculate X (bend) and Y (height) coordinates for every frame.
    # X Bending: Bass/Harmonic pitch frequency random walk or smooth oscillation.
    # We will accumulate a heading direction that shifts based on pitch and beats.
    print("  Pre-calculating 3D track spline offsets...")
    track_points = []
    
    current_x = 0.0
    current_y = 0.0
    heading_x = 0.0
    
    # Apply low-pass filter to smooth the curves
    rms_smooth = np.convolve(sampled_rms, np.ones(5)/5.0, mode='same')
    onset_smooth = np.convolve(sampled_onset, np.ones(3)/3.0, mode='same')
    
    # Calculate average energy
    avg_rms = np.mean(sampled_rms)
    
    for i, t in enumerate(sampled_times):
        # Time-varying variables
        rms_val = float(sampled_rms[i]) if i < len(sampled_rms) else 0.0
        onset_val = float(sampled_onset[i]) if i < len(sampled_onset) else 0.0
        chroma = sampled_chroma[i] if i < len(sampled_chroma) else [0.0]*12
        
        # 1. X Offset (Curves):
        # We nudge heading_x based on dominant pitch class or beats
        # Dominant pitch index (0-11)
        dom_pitch = int(np.argmax(chroma))
        # Map pitch classes to direction: C=0, C#=1, etc.
        # Let's say odd pitch index goes left, even goes right
        pitch_dir = -1.0 if dom_pitch % 2 == 0 else 1.0
        
        # Nudge heading: onset peaks trigger direction shifts
        if onset_val > 1.2:
            heading_x += pitch_dir * 0.3 * onset_val
            
        # Limit heading to avoid spinning out of control
        heading_x = np.clip(heading_x, -1.8, 1.8)
        
        # Slowly decay heading towards center when song is quiet
        heading_x *= 0.97
        
        # Accumulate X offset
        current_x += heading_x * (1.0 / args.fps) * 5.0
        current_x = np.clip(current_x, -12.0, 12.0) # boundaries
        
        # 2. Y Offset (Hills & Slopes):
        # Leaky integrator to prevent clipping and ensure continuous ups and downs
        rms_diff = rms_val - avg_rms
        
        # Add a major bump/jump when there is a strong drum/onset beat
        onset_bump = 0.0
        if onset_val > 1.4:
            onset_bump = (onset_val - 1.4) * 8.0 # jump up
            
        # Slope change integrates volume changes, but decays back to 0
        current_y = current_y * 0.94 + (rms_diff * 22.0) + onset_bump
        
        # Add a baseline sine wave to guarantee minor rolling hills
        sine_hill = np.sin(t * 0.35) * 6.5
        total_y = current_y + sine_hill
        total_y = np.clip(total_y, -50.0, 50.0) # boundaries
        
        track_points.append({
            "time": float(t),
            "x": float(current_x),
            "y": float(total_y),
            "rms": rms_val,
            "onset": onset_val,
            "chroma": chroma
        })
        
    # Write analysis to file
    analysis_data = {
        "bpm": bpm,
        "bar_lines": bar_lines,
        "beats": beat_times,
        "notes": notes,
        "track_points": track_points
    }
    
    # Ensure directory exists
    output_dir = os.path.dirname(args.output)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
        
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(analysis_data, f, ensure_ascii=False, indent=2)
        
    print(f"  Successfully wrote analysis to: {args.output}")

if __name__ == "__main__":
    main()
