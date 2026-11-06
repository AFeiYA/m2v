from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


_DIALOGUE_PREFIX = "Dialogue:"
_OVERRIDE_TAG_RE = re.compile(r"\{[^}]*\}")
_ASS_NEWLINE_RE = re.compile(r"\\[Nn]")


def seconds_to_lrc_time(seconds: float) -> str:
	"""Format float seconds as mm:ss.xx LRC timestamp."""
	total_centis = int(round(max(0.0, float(seconds)) * 100))
	total_seconds = total_centis // 100
	centis = total_centis % 100
	minutes = total_seconds // 60
	secs = total_seconds % 60
	return f"{minutes:02d}:{secs:02d}.{centis:02d}"


def _convert_lrc_script(text: str, target_lang: str | None) -> str:
	if not text or not target_lang:
		return text
	lower = str(target_lang).strip().lower().replace("_", "-")
	if lower in ("zh-hant", "zh-tw", "zh-hk", "zh-mo", "trad"):
		try:
			import opencc

			return opencc.OpenCC("s2t").convert(text)
		except Exception:
			return text
	elif lower in ("zh-hans", "zh-cn", "zh", "simp"):
		try:
			import opencc

			return opencc.OpenCC("t2s").convert(text)
		except Exception:
			return text
	return text


def _format_pinyin_line(text: str) -> str:
	if not text or not re.search(r"[\u4e00-\u9fff]", text):
		return ""
	try:
		from pypinyin import Style, pinyin

		py_list = pinyin(text, style=Style.TONE)
		return " ".join(p[0] for p in py_list if p and p[0].strip())
	except Exception:
		return ""


def alignment_to_lrc(
	alignment: Any,
	title: str = "",
	artist: str = "",
	*,
	enhanced: bool = False,
	lang: str | None = None,
	pinyin: bool = False,
) -> str:
	"""Convert alignment data (AlignmentResult, dict, or list of lines) to standard LRC format."""
	lines_data = []
	meta_title = title
	meta_artist = artist

	if hasattr(alignment, "lines"):
		lines_data = getattr(alignment, "lines") or []
		meta_title = meta_title or getattr(alignment, "title", "") or ""
		meta_artist = meta_artist or getattr(alignment, "artist", "") or ""
	elif isinstance(alignment, dict):
		lines_data = alignment.get("lines") or alignment.get("sentences") or []
		meta_title = meta_title or alignment.get("title") or alignment.get("song_title") or ""
		meta_artist = meta_artist or alignment.get("artist") or ""
	elif isinstance(alignment, list):
		lines_data = alignment

	if lang:
		meta_title = _convert_lrc_script(meta_title, lang)
		meta_artist = _convert_lrc_script(meta_artist, lang)

	out: list[str] = []
	if meta_title:
		out.append(f"[ti:{meta_title.strip()}]")
	if meta_artist:
		out.append(f"[ar:{meta_artist.strip()}]")
	out.append("[by:Fovea MV]")

	for line in lines_data:
		if hasattr(line, "start"):
			start = getattr(line, "start")
			text = getattr(line, "text", "") or ""
			words = getattr(line, "words", None) or []
		elif isinstance(line, dict):
			start = line.get("start", 0.0)
			text = line.get("text", "") or ""
			words = line.get("words") or []
		else:
			continue

		start_time_str = seconds_to_lrc_time(float(start))
		clean_text = " ".join(str(text).strip().split())
		if not clean_text and words:
			clean_text = "".join(
				(w.get("word", "") if isinstance(w, dict) else getattr(w, "word", ""))
				for w in words
			).strip()

		if not clean_text and not words:
			continue

		if lang:
			clean_text = _convert_lrc_script(clean_text, lang)

		if enhanced and words:
			word_parts = []
			for w in words:
				w_start = w.get("start", 0.0) if isinstance(w, dict) else getattr(w, "start", 0.0)
				w_text = w.get("word", "") if isinstance(w, dict) else getattr(w, "word", "")
				if lang:
					w_text = _convert_lrc_script(w_text, lang)
				word_parts.append(f"<{seconds_to_lrc_time(float(w_start))}>{w_text}")
			line_str = f"[{start_time_str}]{''.join(word_parts) if word_parts else clean_text}"
		else:
			line_str = f"[{start_time_str}]{clean_text}"

		if pinyin:
			py_line = _format_pinyin_line(clean_text)
			if py_line:
				out.append(f"[{start_time_str}]{py_line}")
		out.append(line_str)

	return "\n".join(out) + "\n"


def convert_alignment_to_lrc(
	input_path: Path,
	output_path: Path | None = None,
	title: str = "",
	artist: str = "",
	*,
	enhanced: bool = False,
	lang: str | None = None,
	pinyin: bool = False,
) -> Path:
	"""Read alignment JSON file, convert to LRC, and write to output_path."""
	if output_path is None:
		output_path = input_path.with_suffix(".lrc")
	raw = json.loads(input_path.read_text(encoding="utf-8"))
	content = alignment_to_lrc(
		raw, title=title, artist=artist, enhanced=enhanced, lang=lang, pinyin=pinyin
	)
	output_path.parent.mkdir(parents=True, exist_ok=True)
	output_path.write_text(content, encoding="utf-8")
	return output_path


def convert_ass_to_lrc(input_path: Path, output_path: Path | None = None) -> Path:
	"""Convert ASS dialogue lines to line-based LRC."""
	if output_path is None:
		output_path = input_path.with_suffix(".lrc")

	lrc_lines = ass_text_to_lrc(input_path.read_text(encoding="utf-8-sig"))
	output_path.write_text("\n".join(lrc_lines) + "\n", encoding="utf-8")
	return output_path


def ass_text_to_lrc(ass_text: str) -> list[str]:
	"""Convert ASS text content to a list of LRC lines."""
	event_format: list[str] | None = None
	lrc_lines: list[str] = []

	for raw_line in ass_text.splitlines():
		line = raw_line.strip()
		if not line:
			continue

		if line.startswith("Format:"):
			fields = [field.strip().lower() for field in line[len("Format:"):].split(",")]
			if "start" in fields and "text" in fields:
				event_format = fields
			continue

		if not line.startswith(_DIALOGUE_PREFIX):
			continue

		if event_format is None:
			raise ValueError("ASS [Events] section is missing a usable Format line")

		dialogue_payload = line[len(_DIALOGUE_PREFIX):].lstrip()
		parts = [part.strip() for part in dialogue_payload.split(",", len(event_format) - 1)]
		if len(parts) != len(event_format):
			continue

		record = dict(zip(event_format, parts))
		text = _clean_ass_text(record.get("text", ""))
		if not text:
			continue

		start = _ass_time_to_lrc(record["start"])
		lrc_lines.append(f"[{start}]{text}")

	return lrc_lines


def _clean_ass_text(text: str) -> str:
	text = _OVERRIDE_TAG_RE.sub("", text)
	text = _ASS_NEWLINE_RE.sub(" ", text)
	return " ".join(text.strip().split())


def _ass_time_to_lrc(value: str) -> str:
	match = re.fullmatch(r"(?P<hours>\d+):(?P<minutes>\d{2}):(?P<seconds>\d{2})\.(?P<centis>\d{2})", value)
	if not match:
		raise ValueError(f"Invalid ASS timestamp: {value}")

	total_minutes = int(match.group("hours")) * 60 + int(match.group("minutes"))
	seconds = int(match.group("seconds"))
	centis = int(match.group("centis"))
	return f"{total_minutes:02d}:{seconds:02d}.{centis:02d}"


def build_arg_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description="Convert ASS karaoke subtitles or alignment JSON to LRC")
	parser.add_argument("input", type=Path, help="Path to .ass subtitle file or .json alignment file")
	parser.add_argument("-o", "--output", type=Path, help="Path to output .lrc file")
	parser.add_argument("--enhanced", action="store_true", help="Include word-level timestamps in LRC")
	return parser


def main() -> None:
	args = build_arg_parser().parse_args()
	if args.input.suffix.lower() == ".json":
		output_path = convert_alignment_to_lrc(args.input, args.output, enhanced=args.enhanced)
	else:
		output_path = convert_ass_to_lrc(args.input, args.output)
	print(output_path)


if __name__ == "__main__":
	main()