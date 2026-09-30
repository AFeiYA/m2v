from pathlib import Path

from src.config import PipelineConfig
from src.storyboard_schema import AlignmentProject, AlignedLine, SongAnalysis


def test_reused_alignment_gets_analysis_without_realigning(tmp_path, monkeypatch):
    import src.audio_analyzer as analyzer
    import src.subtitle as subtitle
    import src.aligner as aligner
    from src.main import process_one
    audio = tmp_path / 'song.mp3'
    audio.write_bytes(b'original mix')
    source = tmp_path / 'song_alignment.json'
    project = AlignmentProject(lines=[AlignedLine(text='保留歌词', start=1, end=3)])
    project.save_json(source)
    output = tmp_path / 'output'
    output.mkdir()
    inputs = []
    def analyze(path, cache_path, **kwargs):
        inputs.append(Path(path))
        return SongAnalysis(duration=8, bpm=120, metadata={'cache_hit': False})
    def generate(project, path, *args, **kwargs):
        assert project.analysis is not None
        Path(path).write_text('ASS fixture')
    def forbidden(*args, **kwargs):
        raise AssertionError('Analysis must not rerun CTC')
    monkeypatch.setattr(analyzer, 'cached_audio_analysis', analyze)
    monkeypatch.setattr(subtitle, 'generate_ass', generate)
    monkeypatch.setattr(aligner, 'align_lyrics', forbidden)
    progress = []
    result = process_one(audio, None, output, None, PipelineConfig(alignment_json=source, ass_only=True), on_progress=lambda *args: progress.append(args))
    assert result.exists()
    saved = AlignmentProject.load_json(output / 'song_alignment.json')
    assert saved.lines == project.lines
    assert saved.duration == 8 and saved.analysis.bpm == 120
    assert inputs == [audio]
    assert any(step == 'analyzing' for step, _, _ in progress)
