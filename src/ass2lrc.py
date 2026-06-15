from __future__ import annotations

import argparse
import re
from pathlib import Path


_DIALOGUE_PREFIX = "Dialogue:"
_OVERRIDE_TAG_RE = re.compile(r"\{[^}]*\}")
_ASS_NEWLINE_RE = re.compile(r"\\[Nn]")


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
	parser = argparse.ArgumentParser(description="Convert ASS karaoke subtitles to LRC")
	parser.add_argument("input", type=Path, help="Path to .ass subtitle file")
	parser.add_argument("-o", "--output", type=Path, help="Path to output .lrc file")
	return parser


def main() -> None:
	args = build_arg_parser().parse_args()
	output_path = convert_ass_to_lrc(args.input, args.output)
	print(output_path)


if __name__ == "__main__":
	main()