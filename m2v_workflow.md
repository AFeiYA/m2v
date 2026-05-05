# M2V Project Development Skill

This file provides the standard operating procedures for the M2V (Music to Video) project. It ensures that the AI assistant uses the correct environment and follows the project's design patterns.

## Environment Setup
Always use the `m2v` conda environment.
- **Run command**: `conda run -n m2v python <command>`
- **Activate manually**: `conda activate m2v`

## Core Operations

### 1. Run Full Pipeline
To process a song from scratch:
```bash
python -m src.main -i ./input/song.wav -o ./output
```

### 2. Start Local Editor
To adjust word timings manually:
```bash
python -m src.local_editor
```
URL: `http://127.0.0.1:8765`

### 3. Regenerate ASS Subtitles
After editing the `_alignment.json`, use this to refresh the `.ass` file:
```bash
python -m src.edit_ass ./output/song_alignment.json -o ./output --no-interactive
```

### 4. Storyboard & Asset Management
In the local editor, you can now manage background images/videos per time range:
- Use **"选择素材"** to browse `input/` and `assets/` directories.
- Use **"同步选中行"** to quickly set start/end times to the current lyric line.
- Events are saved into the `alignment.json` under the `storyboard` field.

### 5. Fetch from Suno
To download audio and lyrics from a Suno URL:
```bash
python -m src.suno_fetch https://suno.com/song/<id>
```

## Styling Guide (Apple Music)

### Vertical Positioning
Adjust `center_y` in `src/subtitle.py` to move the focus line up or down.
- Recommended: `config.font_size * 4.5` (approx 1/3 from top).

### Karaoke Effect
Controlled by `config.use_karaoke_gradient`:
- `True`: Uses `\kf` (smooth sweeping gradient). Note: may cause 1px bleed in some fonts.
- `False`: Uses `\k` (discrete jump). Most stable.

### Motion Physics
- Transition Duration: `0.6s`
- Delay Step: `0.09s` per line (cascading jelly effect).

## Troubleshooting

### FFmpeg Permission Denied
If FFmpeg fails to overwrite the MP4, ensure the file is not open in a video player.

### Karaoke Bleed
If using `\kf` results in a 1px white line on upcoming characters:
- Reset spacing: `\fsp0`.
- Add ZWSP: Append `\u200b` to words (use with caution).
- Use `\k` as a fallback.
