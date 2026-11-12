#!/usr/bin/env python3
"""
Generate complete, broadcast-grade multi-track accompaniment MIDI for Jingle Bells.
Complete structure: Intro (4 bars) -> Verse 1 (8 bars) -> Chorus 1 (8 bars) ->
                    Verse 2 (8 bars) -> Chorus 2 (8 bars) -> Interlude (4 bars) ->
                    Verse 3 (8 bars) -> Chorus 3 (8 bars) ->
                    Verse 4 (8 bars) -> Chorus 4 (8 bars) -> Outro (4 bars).

Standard GM Multi-tracks:
1. Conductor & Markers
2. Grand Piano (Chords & Rhythm comping)
3. Walking Bass (Root-fifth bassline)
4. Sleigh Bells & Percussion (GM Channel 10: Sleigh bells, Kick, Snare, Hi-hat, Crash)
5. Glockenspiel & Celesta (High holiday bell sparkle)
6. Orchestral Strings (Lush holiday warmth)
7. Guide Melody (Full vocal lead melody for reference/singers)
"""

import struct
from pathlib import Path

TICKS_PER_BEAT = 480
Q = TICKS_PER_BEAT          # Quarter note (1 beat) = 480
E_LEN = TICKS_PER_BEAT // 2  # Eighth note (0.5 beat) = 240
H = TICKS_PER_BEAT * 2      # Half note (2 beats) = 960
DH = TICKS_PER_BEAT * 3     # Dotted half (3 beats) = 1440
W = TICKS_PER_BEAT * 4      # Whole note (4 beats / 1 bar) = 1920

def vlq(n):
    res = bytearray()
    res.append(n & 0x7F)
    n >>= 7
    while n > 0:
        res.append((n & 0x7F) | 0x80)
        n >>= 7
    res.reverse()
    return bytes(res)

class Track:
    def __init__(self, name=""):
        self.events = []
        if name:
            self.add_meta(0, 0x03, name.encode("utf-8"))

    def add_meta(self, at_time, m_type, data):
        self.events.append((at_time, b"\xFF" + bytes([m_type]) + vlq(len(data)) + data))

    def note(self, at_time, ch, pitch, dur, vel=90):
        # Note on
        self.events.append((at_time, bytes([0x90 | ch, pitch, vel])))
        # Note off
        self.events.append((at_time + dur, bytes([0x80 | ch, pitch, 0])))

    def chord(self, at_time, ch, pitches, dur, vel=85):
        for p in pitches:
            self.note(at_time, ch, p, dur, vel)

    def program_change(self, at_time, ch, prog):
        self.events.append((at_time, bytes([0xC0 | ch, prog])))

    def build(self):
        sorted_ev = sorted(self.events, key=lambda x: x[0])
        body = bytearray()
        cur_t = 0
        for t, ev in sorted_ev:
            delta = t - cur_t
            body.extend(vlq(delta))
            body.extend(ev)
            cur_t = t
        body.extend(vlq(0) + b"\xFF\x2F\x00") # End of Track
        return b"MTrk" + struct.pack(">I", len(body)) + body

# Note definitions
C2, D2, E2, F2, G2, A2, B2 = 36, 38, 40, 41, 43, 45, 47
C3, D3, E3, F3, G3, A3, B3 = 48, 50, 52, 53, 55, 57, 59
C4, D4, E4, F4, G4, A4, B4 = 60, 62, 64, 65, 67, 69, 71
C5, D5, E5, F5, G5, A5, B5 = 72, 74, 76, 77, 79, 81, 83
C6, D6, E6, G6 = 84, 86, 88, 91

# Chords (Pitches)
CHORD_C = [C4, E4, G4]
CHORD_F = [C4, F4, A4]
CHORD_G = [B3, D4, G4]
CHORD_G7 = [B3, D4, F4, G4]
CHORD_D7 = [C4, D4, F4 + 1, A4] # F#4

# Drums (GM Ch 10 = ch 9)
DRUM_KICK = 36
DRUM_SNARE = 38
DRUM_SIDE_STICK = 37
DRUM_HIHAT_CLOSED = 42
DRUM_HIHAT_OPEN = 46
DRUM_TAMBOURINE_BELLS = 54  # Tambourine / Jingle Bells
DRUM_CRASH = 49
DRUM_RIDE_BELL = 53

def create_full_accompaniment():
    # 7 Tracks
    t_conductor = Track("Conductor & Structure")
    t_piano = Track("Acoustic Grand Piano")
    t_bass = Track("Walking Bass")
    t_bells = Track("Glockenspiel & Celesta")
    t_strings = Track("Holiday Strings")
    t_drums = Track("Sleigh Bells & Christmas Drums")
    t_melody = Track("Lead Vocal Melody Guide")

    # Programs
    t_piano.program_change(0, 0, 0)      # Acoustic Grand Piano
    t_bass.program_change(0, 1, 32)      # Acoustic Bass
    t_bells.program_change(0, 2, 9)      # Celesta / Glockenspiel
    t_strings.program_change(0, 3, 48)   # String Ensemble 1
    t_melody.program_change(0, 4, 11)    # Vibraphone / Music Box guide

    # Conductor: 120 BPM, 4/4
    # Tempo in microseconds per beat: 500000 = 120 BPM
    t_conductor.add_meta(0, 0x51, struct.pack(">I", 500000)[1:])
    # Time signature 4/4
    t_conductor.add_meta(0, 0x58, bytes([4, 2, 24, 8]))

    # Helper to schedule sections
    cur_bar = 0

    def get_bar_time(bar_idx):
        return bar_idx * W

    def add_section_marker(bar_idx, title):
        t_conductor.add_meta(get_bar_time(bar_idx), 0x06, title.encode("utf-8"))

    # Arrangement blocks (bar duration)
    # Verse chord sequence (8 bars in cut-time/standard 4-beat representation):
    # Bar 0: C, Bar 1: C, Bar 2: F, Bar 3: C, Bar 4: C, Bar 5: G7, Bar 6: G7, Bar 7: C
    verse_chords = [
        (CHORD_C, C3, G2),
        (CHORD_C, C3, G2),
        (CHORD_F, F2, C3),
        (CHORD_C, C3, G2),
        (CHORD_C, C3, G2),
        (CHORD_G7, G2, D3),
        (CHORD_G7, G2, D3),
        (CHORD_C, C3, G2),
    ]

    # Chorus chord sequence (8 bars):
    # Bar 0: C, Bar 1: C, Bar 2: F, Bar 3: C, Bar 4: F, Bar 5: C, Bar 6: G7, Bar 7: C
    chorus_chords = [
        (CHORD_C, C3, G2),
        (CHORD_C, C3, G2),
        (CHORD_F, F2, C3),
        (CHORD_C, C3, G2),
        (CHORD_F, F2, C3),
        (CHORD_C, C3, G2),
        (CHORD_G7, G2, D3),
        (CHORD_C, C3, G2),
    ]

    # Melody patterns (relative to start of section in beats)
    # Verse melody:
    # Dashing through the snow (G4 E4 D4 C4 | G4 - - -)
    # in a one-horse open sleigh (G4 G4 E4 D4 | C4 A4 - -)
    # O'er the fields we go (A4 F4 E4 D4 | B4 - - -)
    # laughing all the way (G4 G4 F4 D4 | E4 - - -)
    # ...
    verse_melody_events = [
        # Bar 0: G4 E4 D4 C4
        (0, G4, Q), (Q, E4, Q), (Q*2, D4, Q), (Q*3, C4, Q),
        # Bar 1: G4 - - -
        (W, G4, H), (W + H, G4, H),
        # Bar 2: in a one-horse open sleigh
        (W*2, G4, E_LEN), (W*2 + E_LEN, G4, E_LEN), (W*2 + Q, E4, Q), (W*2 + Q*2, D4, Q), (W*2 + Q*3, C4, Q),
        # Bar 3: A4
        (W*3, A4, DH),
        # Bar 4: O'er the fields we go
        (W*4, A4, Q), (W*4 + Q, F4, Q), (W*4 + Q*2, E4, Q), (W*4 + Q*3, D4, Q),
        # Bar 5: B4
        (W*5, B4, DH),
        # Bar 6: laughing all the way
        (W*6, G4, Q), (W*6 + Q, G4, Q), (W*6 + Q*2, F4, Q), (W*6 + Q*3, D4, Q),
        # Bar 7: C4 / E4
        (W*7, E4, DH),
    ]

    # Chorus melody:
    # Jingle bells, jingle bells, jingle all the way
    # E4 E4 E4 - | E4 E4 E4 - | E4 G4 C4 D4 | E4 - - -
    # O what fun it is to ride in a one-horse open sleigh (hey!)
    # F4 F4 F4 F4 | F4 E4 E4 E4 | E4 D4 D4 E4 | D4 - G4 - (or G4 G4 F4 D4 | C4 - - -)
    chorus_melody_events = [
        # Bar 0: E4 E4 E4 -
        (0, E4, Q), (Q, E4, Q), (Q*2, E4, H),
        # Bar 1: E4 E4 E4 -
        (W, E4, Q), (W + Q, E4, Q), (W + Q*2, E4, H),
        # Bar 2: E4 G4 C4 D4
        (W*2, E4, Q), (W*2 + Q, G4, Q), (W*2 + Q*2, C4, Q), (W*2 + Q*3, D4, Q),
        # Bar 3: E4 - - -
        (W*3, E4, DH),
        # Bar 4: F4 F4 F4 F4
        (W*4, F4, Q), (W*4 + Q, F4, Q), (W*4 + Q*2, F4, Q), (W*4 + Q*3, F4, Q),
        # Bar 5: F4 E4 E4 E4
        (W*5, F4, Q), (W*5 + Q, E4, Q), (W*5 + Q*2, E4, Q), (W*5 + Q*3, E4, Q),
        # Bar 6: G4 G4 F4 D4
        (W*6, G4, Q), (W*6 + Q, G4, Q), (W*6 + Q*2, F4, Q), (W*6 + Q*3, D4, Q),
        # Bar 7: C4 - - -
        (W*7, C4, DH),
    ]

    def render_section(start_bar, chords, is_chorus=False, melody_events=None):
        start_t = get_bar_time(start_bar)
        num_bars = len(chords)

        # Crash cymbal on section downbeat
        t_drums.note(start_t, 9, DRUM_CRASH, Q, vel=95 if is_chorus else 80)

        for b_idx, (chord_notes, root_b, fifth_b) in enumerate(chords):
            b_t = start_t + b_idx * W

            # 1. Piano: Festive bouncy comping (staccato chords on beats 2 & 4, or 1 2 3 4)
            # Beat 1: root accent, Beat 2: chord, Beat 3: chord, Beat 4: chord
            t_piano.chord(b_t, 0, chord_notes, Q - 40, vel=75)
            t_piano.chord(b_t + Q, 0, chord_notes, Q - 40, vel=82)
            t_piano.chord(b_t + Q*2, 0, chord_notes, Q - 40, vel=78)
            t_piano.chord(b_t + Q*3, 0, chord_notes, Q - 40, vel=84)

            # 2. Bass: 1 - 5 walking bounce
            t_bass.note(b_t, 1, root_b, H - 40, vel=90)
            t_bass.note(b_t + H, 1, fifth_b, H - 40, vel=85)

            # 3. Strings: Sustained warm harmony
            t_strings.chord(b_t, 3, [p - 12 for p in chord_notes] + chord_notes[:1], W - 40, vel=65 if not is_chorus else 80)

            # 4. Drums & Sleigh Bells:
            # Sleigh bells on EVERY eighth note (ding ding ding ding ding ding ding ding!)
            for e in range(8):
                t_drums.note(b_t + e * E_LEN, 9, DRUM_TAMBOURINE_BELLS, E_LEN - 30, vel=88 if e % 2 == 0 else 72)
            # Kick on 1 & 3, Snare on 2 & 4
            t_drums.note(b_t, 9, DRUM_KICK, Q, vel=85)
            t_drums.note(b_t + Q, 9, DRUM_SNARE, Q, vel=88)
            t_drums.note(b_t + Q*2, 9, DRUM_KICK, Q, vel=85)
            t_drums.note(b_t + Q*3, 9, DRUM_SNARE, Q, vel=92)
            # Hi-hat on 1, 2, 3, 4
            for beat in range(4):
                t_drums.note(b_t + beat * Q, 9, DRUM_HIHAT_CLOSED, Q - 30, vel=70)

            # 5. Glockenspiel: High octave holiday sparkle on Chorus and every 2nd bar of Verse
            if is_chorus:
                t_bells.note(b_t, 2, chord_notes[-1] + 12, Q, vel=85)
                t_bells.note(b_t + H, 2, chord_notes[0] + 24, Q, vel=80)
            elif b_idx % 2 == 1:
                t_bells.note(b_t + H, 2, chord_notes[0] + 12, Q, vel=70)

        # 6. Melody Guide Track
        if melody_events:
            for rel_t, pitch, dur in melody_events:
                t_melody.note(start_t + rel_t, 4, pitch, dur, vel=95 if is_chorus else 88)

    # -------------------------------------------------------------
    # BUILD COMPLETE SONG
    # -------------------------------------------------------------

    # 1. Intro (4 bars)
    add_section_marker(cur_bar, "Intro")
    intro_chords = [
        (CHORD_C, C3, G2),
        (CHORD_F, F2, C3),
        (CHORD_G7, G2, D3),
        (CHORD_C, C3, G2),
    ]
    render_section(cur_bar, intro_chords, is_chorus=False)
    # Intro glockenspiel sparkle arpeggio
    intro_t = get_bar_time(cur_bar)
    t_bells.note(intro_t, 2, C5, Q, vel=90)
    t_bells.note(intro_t + Q, 2, E5, Q, vel=90)
    t_bells.note(intro_t + Q*2, 2, G5, Q, vel=90)
    t_bells.note(intro_t + Q*3, 2, C6, H, vel=95)
    cur_bar += 4

    # 2. Verse 1 (8 bars)
    add_section_marker(cur_bar, "Verse 1")
    render_section(cur_bar, verse_chords, is_chorus=False, melody_events=verse_melody_events)
    cur_bar += 8

    # 3. Chorus 1 (8 bars)
    add_section_marker(cur_bar, "Chorus 1")
    render_section(cur_bar, chorus_chords, is_chorus=True, melody_events=chorus_melody_events)
    cur_bar += 8

    # 4. Verse 2 (8 bars)
    add_section_marker(cur_bar, "Verse 2")
    render_section(cur_bar, verse_chords, is_chorus=False, melody_events=verse_melody_events)
    cur_bar += 8

    # 5. Chorus 2 (8 bars)
    add_section_marker(cur_bar, "Chorus 2")
    render_section(cur_bar, chorus_chords, is_chorus=True, melody_events=chorus_melody_events)
    cur_bar += 8

    # 6. Interlude / Bells Solo (4 bars)
    add_section_marker(cur_bar, "Festive Interlude")
    interlude_chords = [
        (CHORD_F, F2, C3),
        (CHORD_C, C3, G2),
        (CHORD_G7, G2, D3),
        (CHORD_C, C3, G2),
    ]
    render_section(cur_bar, interlude_chords, is_chorus=True)
    interlude_t = get_bar_time(cur_bar)
    # Joyful bells melody solo
    t_bells.note(interlude_t, 2, A5, Q, vel=95)
    t_bells.note(interlude_t + Q, 2, G5, Q, vel=95)
    t_bells.note(interlude_t + Q*2, 2, F5, Q, vel=95)
    t_bells.note(interlude_t + Q*3, 2, E5, Q, vel=95)
    t_bells.note(interlude_t + W, 2, G5, H, vel=95)
    t_bells.note(interlude_t + W + H, 2, C6, H, vel=100)
    cur_bar += 4

    # 7. Verse 3 (8 bars)
    add_section_marker(cur_bar, "Verse 3")
    render_section(cur_bar, verse_chords, is_chorus=False, melody_events=verse_melody_events)
    cur_bar += 8

    # 8. Chorus 3 (8 bars)
    add_section_marker(cur_bar, "Chorus 3")
    render_section(cur_bar, chorus_chords, is_chorus=True, melody_events=chorus_melody_events)
    cur_bar += 8

    # 9. Verse 4 (8 bars)
    add_section_marker(cur_bar, "Verse 4")
    render_section(cur_bar, verse_chords, is_chorus=False, melody_events=verse_melody_events)
    cur_bar += 8

    # 10. Chorus 4 (8 bars - Grand Finale Chorus)
    add_section_marker(cur_bar, "Final Chorus")
    render_section(cur_bar, chorus_chords, is_chorus=True, melody_events=chorus_melody_events)
    cur_bar += 8

    # 11. Outro (4 bars - Big Christmas Finish!)
    add_section_marker(cur_bar, "Outro Finale")
    outro_t = get_bar_time(cur_bar)
    # Bar 0: F chord
    t_piano.chord(outro_t, 0, CHORD_F, W, vel=90)
    t_bass.note(outro_t, 1, F2, W, vel=95)
    t_strings.chord(outro_t, 3, CHORD_F + [F5], W, vel=88)
    t_drums.note(outro_t, 9, DRUM_CRASH, Q, vel=95)
    for e in range(8):
        t_drums.note(outro_t + e * E_LEN, 9, DRUM_TAMBOURINE_BELLS, E_LEN - 30, vel=85)

    # Bar 1: C chord
    t_piano.chord(outro_t + W, 0, CHORD_C, W, vel=90)
    t_bass.note(outro_t + W, 1, C3, W, vel=95)
    t_strings.chord(outro_t + W, 3, CHORD_C + [G5], W, vel=88)

    # Bar 2: G7 chord with drum roll
    t_piano.chord(outro_t + W*2, 0, CHORD_G7, W, vel=95)
    t_bass.note(outro_t + W*2, 1, G2, W, vel=95)
    t_strings.chord(outro_t + W*2, 3, CHORD_G7 + [B5], W, vel=92)
    # Snare crescendo roll
    for e in range(8):
        t_drums.note(outro_t + W*2 + e * E_LEN, 9, DRUM_SNARE, E_LEN - 20, vel=60 + e * 5)
        t_drums.note(outro_t + W*2 + e * E_LEN, 9, DRUM_TAMBOURINE_BELLS, E_LEN - 20, vel=70 + e * 4)

    # Bar 3: Grand Final C Chord with Crash Cymbal & Glockenspiel High C Chime!
    end_t = outro_t + W*3
    t_piano.chord(end_t, 0, [C3, G3, C4, E4, G4, C5], W*2, vel=110)
    t_bass.note(end_t, 1, C2, W*2, vel=110)
    t_strings.chord(end_t, 3, [C3, G3, C4, E4, G4, C5], W*2, vel=105)
    t_drums.note(end_t, 9, DRUM_CRASH, W, vel=120)
    t_drums.note(end_t, 9, DRUM_KICK, W, vel=115)
    t_bells.note(end_t, 2, C6, W*2, vel=115)
    # Sleigh bells final shake ring out
    t_drums.note(end_t, 9, DRUM_TAMBOURINE_BELLS, W, vel=110)

    # Assemble MIDI File Format 1
    tracks = [t_conductor, t_piano, t_bass, t_bells, t_strings, t_drums, t_melody]
    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), TICKS_PER_BEAT)
    midi_data = header + b"".join(t.build() for t in tracks)

    # Total duration calculation
    total_bars = cur_bar + 4
    total_seconds = (total_bars * 4 * 60) / 120 # 120 BPM, 4 beats/bar
    print(f"Generated Full Jingle Bells Accompaniment MIDI:")
    print(f"  Total Bars: {total_bars}")
    print(f"  Tempo: 120 BPM")
    print(f"  Duration: {int(total_seconds // 60)}m {int(total_seconds % 60):02d}s ({total_seconds:.1f}s)")
    print(f"  Total Tracks: {len(tracks)}")
    return midi_data

if __name__ == "__main__":
    data = create_full_accompaniment()
    
    # Save to Downloads & Project
    out_dl = Path("/Users/luca/Downloads/Jingle_Bells_Full_Accompaniment.mid")
    out_proj = Path("/Users/luca/suno2MV/projects/christmas_album/02_Jingle_Bells/Jingle_Bells_Full_Accompaniment.mid")
    
    out_dl.write_bytes(data)
    out_proj.write_bytes(data)
    print(f"Saved to Downloads: {out_dl} ({len(data)} bytes)")
    print(f"Saved to Project:   {out_proj}")
