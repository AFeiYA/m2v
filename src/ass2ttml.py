from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


_DIALOGUE_PREFIX = "Dialogue:"
_OVERRIDE_TAG_RE = re.compile(r"\{[^}]*\}")
_ASS_NEWLINE_RE = re.compile(r"\\[Nn]")


def escape_xml(text: str) -> str:
	"""Escape special XML characters."""
	return (
		str(text)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
		.replace("'", "&apos;")
	)


def seconds_to_ttml_time(seconds: float) -> str:
	"""Format float seconds as HH:MM:SS.mmm TTML timestamp."""
	total_ms = int(round(max(0.0, float(seconds)) * 1000))
	ms = total_ms % 1000
	total_s = total_ms // 1000
	secs = total_s % 60
	total_m = total_s // 60
	mins = total_m % 60
	hours = total_m // 60
	return f"{hours:02d}:{mins:02d}:{secs:02d}.{ms:03d}"


def parse_ass_time(timestamp: str) -> float:
	"""Parse an ASS timestamp string (H:MM:SS.cc) into seconds."""
	parts = timestamp.strip().split(":")
	if len(parts) != 3:
		return 0.0
	hours = float(parts[0])
	minutes = float(parts[1])
	seconds = float(parts[2])
	return round(hours * 3600.0 + minutes * 60.0 + seconds, 3)


def alignment_to_ttml(
	alignment: Any,
	title: str = "",
	artist: str = "",
	lang: str = "zh-CN",
) -> str:
	"""Convert alignment data to Apple Music Timed Text Markup Language (TTML) format."""
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

	meta_title = meta_title or "Untitled"
	meta_artist = meta_artist or "Unknown Artist"

	# Compute total duration from max line end
	max_end = 0.0
	for line in lines_data:
		end_val = getattr(line, "end", None) if hasattr(line, "end") else (line.get("end") if isinstance(line, dict) else None)
		if end_val is not None:
			try:
				max_end = max(max_end, float(end_val))
			except (ValueError, TypeError):
				pass

	dur_str = seconds_to_ttml_time(max_end)

	xml_lines = [
		'<?xml version="1.0" encoding="UTF-8"?>',
		'<tt xmlns="http://www.w3.org/ns/ttml"',
		'    xmlns:ttm="http://www.w3.org/ns/ttml#metadata"',
		'    xmlns:itunes="http://music.apple.com/lyric-ttml-extensions"',
		f'    xml:lang="{escape_xml(lang)}">',
		"  <head>",
		"    <metadata>",
		f"      <ttm:title>{escape_xml(meta_title)}</ttm:title>",
		f'      <ttm:agent type="person" xml:id="v1">{escape_xml(meta_artist)}</ttm:agent>',
		"    </metadata>",
		"  </head>",
		f'  <body dur="{dur_str}">',
		"    <div>",
	]

	for line in lines_data:
		if hasattr(line, "start"):
			start = float(getattr(line, "start", 0.0) or 0.0)
			end = float(getattr(line, "end", start + 1.0) or start + 1.0)
			text = getattr(line, "text", "") or ""
			words = getattr(line, "words", None) or []
		elif isinstance(line, dict):
			start = float(line.get("start", 0.0) or 0.0)
			end = float(line.get("end", start + 1.0) or start + 1.0)
			text = line.get("text", "") or ""
			words = line.get("words") or []
		else:
			continue

		clean_text = " ".join(str(text).strip().split())
		if not clean_text and words:
			clean_text = "".join(
				(w.get("word", "") if isinstance(w, dict) else getattr(w, "word", ""))
				for w in words
			).strip()

		if not clean_text and not words:
			continue

		p_begin = seconds_to_ttml_time(start)
		p_end = seconds_to_ttml_time(end)

		if words:
			span_parts = []
			for w in words:
				w_start = float(w.get("start", start) if isinstance(w, dict) else getattr(w, "start", start))
				w_end = float(w.get("end", w_start + 0.3) if isinstance(w, dict) else getattr(w, "end", w_start + 0.3))
				w_text = w.get("word", "") if isinstance(w, dict) else getattr(w, "word", "")
				if not w_text:
					continue
				span_parts.append(
					f'<span begin="{seconds_to_ttml_time(w_start)}" end="{seconds_to_ttml_time(w_end)}">{escape_xml(w_text)}</span>'
				)
			if span_parts:
				xml_lines.append(f'      <p begin="{p_begin}" end="{p_end}">{"".join(span_parts)}</p>')
			else:
				xml_lines.append(f'      <p begin="{p_begin}" end="{p_end}">{escape_xml(clean_text)}</p>')
		else:
			xml_lines.append(f'      <p begin="{p_begin}" end="{p_end}">{escape_xml(clean_text)}</p>')

	xml_lines.extend([
		"    </div>",
		"  </body>",
		"</tt>",
	])

	return "\n".join(xml_lines) + "\n"


def convert_alignment_to_ttml(
	input_path: Path,
	output_path: Path | None = None,
	title: str = "",
	artist: str = "",
	lang: str = "zh-CN",
) -> Path:
	"""Read alignment JSON file, convert to Apple Music TTML, and write to output_path."""
	if output_path is None:
		output_path = input_path.with_suffix(".ttml")
	raw = json.loads(input_path.read_text(encoding="utf-8"))
	content = alignment_to_ttml(raw, title=title, artist=artist, lang=lang)
	output_path.parent.mkdir(parents=True, exist_ok=True)
	output_path.write_text(content, encoding="utf-8")
	return output_path


def ass_text_to_ttml(
	ass_text: str,
	title: str = "",
	artist: str = "",
	lang: str = "zh-CN",
) -> str:
	"""Convert ASS dialogue lines into Apple Music TTML format."""
	event_format: list[str] | None = None
	lines_data: list[dict[str, Any]] = []

	for raw_line in ass_text.splitlines():
		line = raw_line.strip()
		if not line:
			continue
		if line.startswith("Format:"):
			event_format = [field.strip().lower() for field in line.split(":", 1)[1].split(",")]
			continue
		if not line.startswith(_DIALOGUE_PREFIX):
			continue

		payload = line[len(_DIALOGUE_PREFIX) :].strip()
		field_count = len(event_format) if event_format else 10
		parts = [part.strip() for part in payload.split(",", field_count - 1)]
		if len(parts) < field_count:
			continue

		record = dict(zip(event_format or [], parts)) if event_format else {}
		raw_start = record.get("start", parts[1] if len(parts) > 1 else "")
		raw_end = record.get("end", parts[2] if len(parts) > 2 else "")
		raw_text = record.get("text", parts[-1] if parts else "")

		clean_text = _OVERRIDE_TAG_RE.sub("", raw_text)
		clean_text = _ASS_NEWLINE_RE.sub(" ", clean_text)
		clean_text = " ".join(clean_text.split())
		if not clean_text:
			continue

		start_sec = parse_ass_time(raw_start)
		end_sec = parse_ass_time(raw_end)
		lines_data.append({"start": start_sec, "end": end_sec, "text": clean_text})

	return alignment_to_ttml({"lines": lines_data}, title=title, artist=artist, lang=lang)


def main() -> int:
	parser = argparse.ArgumentParser(description="Convert alignment JSON or ASS to Apple Music TTML")
	parser.add_argument("input", type=Path, help="Input alignment.json or subtitles.ass file")
	parser.add_argument("-o", "--output", type=Path, default=None, help="Output .ttml file")
	parser.add_argument("--title", type=str, default="", help="Song title for TTML metadata")
	parser.add_argument("--artist", type=str, default="", help="Artist name for TTML metadata")
	parser.add_argument("--lang", type=str, default="zh-CN", help="Language code (default: zh-CN)")
	args = parser.parse_args()

	in_file: Path = args.input
	if not in_file.exists():
		print(f"Error: input file {in_file} does not exist.")
		return 1

	if in_file.suffix.lower() == ".json":
		out_file = convert_alignment_to_ttml(
			in_file, args.output, title=args.title, artist=args.artist, lang=args.lang
		)
	elif in_file.suffix.lower() == ".ass":
		out_file = args.output or in_file.with_suffix(".ttml")
		ttml_text = ass_text_to_ttml(
			in_file.read_text(encoding="utf-8-sig"),
			title=args.title,
			artist=args.artist,
			lang=args.lang,
		)
		out_file.parent.mkdir(parents=True, exist_ok=True)
		out_file.write_text(ttml_text, encoding="utf-8")
	else:
		print("Error: input file must be .json or .ass")
		return 1

	print(f"Exported TTML: {out_file}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
