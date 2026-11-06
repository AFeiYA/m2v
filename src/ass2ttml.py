from __future__ import annotations

import argparse
import difflib
import json
import re
import urllib.parse
from pathlib import Path
from typing import Any


_DIALOGUE_PREFIX = "Dialogue:"
_OVERRIDE_TAG_RE = re.compile(r"\{[^}]*\}")
_ASS_NEWLINE_RE = re.compile(r"\\[Nn]")

# Common distinct Traditional-Simplified character pairs used for fallback language detection
_TRAD_SIMP_PAIRS = (
	("愛", "爱"), ("風", "风"), ("雲", "云"), ("夢", "梦"), ("飛", "飞"),
	("傷", "伤"), ("淚", "泪"), ("誰", "谁"), ("遠", "远"), ("見", "见"),
	("離", "离"), ("邊", "边"), ("聽", "听"), ("語", "语"), ("話", "话"),
	("聲", "声"), ("詞", "词"), ("會", "会"), ("動", "动"), ("變", "变"),
	("換", "换"), ("點", "点"), ("樣", "样"), ("歲", "岁"), ("懷", "怀"),
	("戀", "恋"), ("憶", "忆"), ("歸", "归"), ("尋", "寻"), ("難", "难"),
	("獨", "独"), ("樂", "乐"), ("牽", "牵"), ("續", "续"), ("終", "终"),
	("覺", "觉"), ("間", "间"), ("問", "问"), ("關", "关"), ("開", "开"),
	("門", "门"), ("頭", "头"), ("臉", "脸"), ("發", "发"), ("帶", "带"),
	("隨", "随"), ("處", "处"), ("別", "别"), ("盡", "尽"), ("雙", "双"),
	("線", "线"), ("轉", "转"), ("車", "车"), ("輕", "轻"), ("選", "选"),
	("進", "进"), ("遺", "遗"), ("還", "还"), ("這", "这"), ("麼", "么"),
	("給", "给"), ("讓", "让"), ("請", "请"), ("說", "说"), ("讀", "读"),
	("們", "们"), ("國", "国"), ("時", "时"), ("經", "经"), ("學", "学"),
	("對", "对"), ("長", "长"), ("兩", "两"), ("條", "条"), ("實", "实"),
	("東", "东"), ("電", "电"), ("幾", "几"), ("後", "后"), ("當", "当"),
	("過", "过"), ("來", "来"), ("氣", "气"), ("無", "无"), ("書", "书"),
	("應", "应"), ("體", "体"), ("歡", "欢"), ("萬", "万"), ("視", "视"),
	("傳", "传"), ("華", "华"), ("熱", "热"), ("與", "与"), ("為", "为"),
	("齊", "齐"), ("雜", "杂"), ("陽", "阳"), ("陰", "阴"), ("隱", "隐"),
	("紅", "红"), ("綠", "绿"), ("藍", "蓝"), ("銀", "银"), ("錢", "钱"),
	("鐘", "钟"), ("鏡", "镜"), ("輪", "轮"), ("載", "载"), ("輝", "辉"),
	("嘆", "叹"), ("雖", "虽"), ("癡", "痴"), ("絲", "丝"), ("織", "织"),
	("編", "编"), ("細", "细"), ("緊", "紧"), ("調", "调"), ("談", "谈"),
	("誤", "误"), ("證", "证"), ("譜", "谱"), ("譯", "译"), ("誠", "诚"),
	("諾", "诺"), ("謊", "谎"), ("謎", "谜"), ("謝", "谢")
)
_COMMON_TRAD_CHARS = frozenset(t for t, _ in _TRAD_SIMP_PAIRS)
_COMMON_SIMP_CHARS = frozenset(s for _, s in _TRAD_SIMP_PAIRS)


def sanitize_download_filename(name: str, fallback: str = "lyrics") -> str:
	"""Sanitize a filename for download, preserving valid unicode characters."""
	cleaned = re.sub(r'[\r\n\t\"\'/\\<>:*?|]', "_", str(name or "")).strip(". ")
	return cleaned or fallback


def make_content_disposition(filename: str, ext: str = "") -> str:
	"""Generate RFC 6266 / RFC 5987 compliant Content-Disposition header with UTF-8 encoding.

	Includes an ASCII fallback to avoid Starlette/Uvicorn latin-1 header encoding errors,
	and an RFC 5987 filename*=UTF-8''... parameter so modern browsers preserve Chinese filenames.
	"""
	safe_name = sanitize_download_filename(filename)
	ext_clean = ext.lstrip(".") if ext else ""
	full_filename = f"{safe_name}.{ext_clean}" if ext_clean else safe_name

	ascii_base = re.sub(r"[^\x20-\x7e]", "_", safe_name).strip(" _")
	if not ascii_base or ascii_base == "_":
		ascii_base = "lyrics"
	ascii_filename = f"{ascii_base}.{ext_clean}" if ext_clean else ascii_base

	quoted_filename = urllib.parse.quote(full_filename, encoding="utf-8")
	return f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{quoted_filename}'


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


def extract_lyric_text(data: Any) -> str:
	"""Extract plain lyric text from string, alignment dict, object, or list of lines."""
	if data is None:
		return ""
	if isinstance(data, str):
		cleaned = _OVERRIDE_TAG_RE.sub("", data)
		lines: list[str] = []
		for line in cleaned.splitlines():
			line_str = line.strip()
			if line_str.startswith(_DIALOGUE_PREFIX):
				parts = line_str.split(",", 9)
				if len(parts) >= 10:
					lines.append(parts[9])
				else:
					lines.append(parts[-1])
			elif not line_str.startswith("[") and not line_str.startswith("Format:"):
				lines.append(line_str)
		return " ".join(lines) if lines else cleaned

	lines_data: list[Any] = []
	if hasattr(data, "lines"):
		lines_data = getattr(data, "lines") or []
	elif isinstance(data, dict):
		lines_data = data.get("lines") or data.get("sentences") or []
		if not lines_data and "text" in data:
			return str(data["text"])
	elif isinstance(data, list):
		lines_data = data

	texts: list[str] = []
	for item in lines_data:
		if isinstance(item, str):
			texts.append(item)
		elif hasattr(item, "text"):
			t = getattr(item, "text", "") or ""
			if t:
				texts.append(str(t))
			words = getattr(item, "words", None) or []
			for w in words:
				wt = getattr(w, "word", "") if hasattr(w, "word") else (w.get("word", "") if isinstance(w, dict) else "")
				if wt:
					texts.append(str(wt))
		elif isinstance(item, dict):
			t = item.get("text") or ""
			if t:
				texts.append(str(t))
			for w in item.get("words") or []:
				if isinstance(w, dict):
					wt = w.get("word") or ""
					if wt:
						texts.append(str(wt))

	return " ".join(texts)


def detect_lyric_lang(text_or_alignment: Any) -> str:
	"""Detect lyric language code compliant with Apple Music TTML specification.

	Returns:
		- "en": predominantly Latin / English letters
		- "zh-Hant": predominantly Traditional Chinese characters
		- "zh-Hans": predominantly Simplified Chinese characters (and default fallback)
	"""
	raw_text = extract_lyric_text(text_or_alignment)
	if not raw_text or not raw_text.strip():
		return "zh-Hans"

	han_chars = re.findall(r"[\u4e00-\u9fff]", raw_text)
	latin_chars = re.findall(r"[a-zA-Z]", raw_text)

	# Predominantly Latin / English
	if len(latin_chars) > len(han_chars):
		return "en"

	# If no Chinese characters found and not English (e.g. only numbers, symbols, instrumental)
	if not han_chars:
		return "zh-Hans"

	han_text = "".join(han_chars)
	try:
		import opencc

		t2s = opencc.OpenCC("t2s")
		s2t = opencc.OpenCC("s2t")
		s_converted = t2s.convert(han_text)
		t_converted = s2t.convert(han_text)

		sm_s = difflib.SequenceMatcher(None, han_text, s_converted)
		diff_to_simp = sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in sm_s.get_opcodes() if tag != "equal")

		sm_t = difflib.SequenceMatcher(None, han_text, t_converted)
		diff_to_trad = sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in sm_t.get_opcodes() if tag != "equal")

		if diff_to_simp > diff_to_trad:
			return "zh-Hant"
		return "zh-Hans"
	except Exception:
		trad_count = sum(1 for c in han_chars if c in _COMMON_TRAD_CHARS)
		simp_count = sum(1 for c in han_chars if c in _COMMON_SIMP_CHARS)
		if trad_count > simp_count:
			return "zh-Hant"
		return "zh-Hans"


def normalize_ttml_lang(lang: str | None) -> str:
	"""Normalize a language tag to conform to Apple Music TTML specification.

	Apple Music Spec (Script Languages):
	- Simplified Chinese: zh-Hans (cannot use zh or zh-CN)
	- Traditional Chinese: zh-Hant
	- English: en (or en-US / en-GB)
	"""
	if not lang:
		return ""
	cleaned = str(lang).strip()
	lower = cleaned.lower().replace("_", "-")
	if lower in ("zh-cn", "zh-sg", "zh-hans", "zh"):
		return "zh-Hans"
	if lower in ("zh-tw", "zh-hk", "zh-mo", "zh-hant"):
		return "zh-Hant"
	if lower.startswith("en"):
		if lower in ("en", "en-us", "en-gb"):
			return cleaned
		return "en"
	return cleaned


def convert_script(text: str, target_lang: str) -> str:
	"""Convert Chinese text script to traditional or simplified if requested."""
	if not text:
		return ""
	if target_lang == "zh-Hant":
		try:
			import opencc

			return opencc.OpenCC("s2t").convert(text)
		except Exception:
			return text
	elif target_lang == "zh-Hans":
		try:
			import opencc

			return opencc.OpenCC("t2s").convert(text)
		except Exception:
			return text
	return text


def format_ruby_spans(text: str, start_str: str = "", end_str: str = "") -> str:
	"""Format Han characters with W3C TTML ruby tags and pinyin."""
	if not text:
		return ""
	timing = f' begin="{start_str}" end="{end_str}"' if start_str and end_str else ""
	if not re.search(r"[\u4e00-\u9fff]", text):
		return f"<span{timing}>{escape_xml(text)}</span>" if timing else escape_xml(text)

	try:
		from pypinyin import Style, pinyin

		py_list = pinyin(text, style=Style.TONE)
		chars = list(text)
		if len(chars) == len(py_list):
			spans = []
			for c, py in zip(chars, py_list):
				if re.match(r"[\u4e00-\u9fff]", c):
					spans.append(
						f'<span tts:ruby="container">'
						f'<span tts:ruby="base"{timing}>{escape_xml(c)}</span>'
						f'<span tts:ruby="textContainer">'
						f'<span tts:ruby="text"{timing}>{escape_xml(py[0])}</span>'
						f"</span></span>"
					)
				else:
					spans.append(f"<span{timing}>{escape_xml(c)}</span>" if timing else escape_xml(c))
			return "".join(spans)
		else:
			py_full = " ".join(p[0] for p in py_list)
			return (
				f'<span tts:ruby="container">'
				f'<span tts:ruby="base"{timing}>{escape_xml(text)}</span>'
				f'<span tts:ruby="textContainer">'
				f'<span tts:ruby="text"{timing}>{escape_xml(py_full)}</span>'
				f"</span></span>"
			)
	except Exception:
		return f"<span{timing}>{escape_xml(text)}</span>" if timing else escape_xml(text)


def alignment_to_ttml(
	alignment: Any,
	title: str = "",
	artist: str = "",
	lang: str | None = None,
	ruby: str | bool | None = None,
) -> str:
	"""Convert alignment data to Apple Music Timed Text Markup Language (TTML) format.

	If lang is omitted or empty, it will be automatically detected from the lyric text.
	If ruby is enabled (e.g. ruby="pinyin" or True), Han characters will be wrapped in
	W3C TTML <span tts:ruby="container"> blocks with pinyin pronunciation.
	"""
	if not lang or str(lang).strip().lower() == "auto":
		resolved_lang = detect_lyric_lang(alignment)
	else:
		resolved_lang = normalize_ttml_lang(lang) or "zh-Hans"

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

	if resolved_lang in ("zh-Hant", "zh-Hans"):
		meta_title = convert_script(meta_title, resolved_lang)
		meta_artist = convert_script(meta_artist, resolved_lang)

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
		'    xmlns:tts="http://www.w3.org/ns/ttml#styling"',
		'    xmlns:itunes="http://music.apple.com/lyric-ttml-extensions"',
		f'    xml:lang="{escape_xml(resolved_lang)}">',
		"  <head>",
		"    <metadata>",
		f"      <ttm:title>{escape_xml(meta_title)}</ttm:title>",
		f'      <ttm:agent type="person" xml:id="v1">{escape_xml(meta_artist)}</ttm:agent>',
		"    </metadata>",
		"  </head>",
		f'  <body dur="{dur_str}">',
		"    <div>",
	]

	use_ruby = bool(ruby)

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

		if resolved_lang in ("zh-Hant", "zh-Hans"):
			clean_text = convert_script(clean_text, resolved_lang)

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
				if resolved_lang in ("zh-Hant", "zh-Hans"):
					w_text = convert_script(w_text, resolved_lang)

				w_begin_str = seconds_to_ttml_time(w_start)
				w_end_str = seconds_to_ttml_time(w_end)

				if use_ruby:
					span_parts.append(format_ruby_spans(w_text, w_begin_str, w_end_str))
				else:
					span_parts.append(
						f'<span begin="{w_begin_str}" end="{w_end_str}">{escape_xml(w_text)}</span>'
					)
			if span_parts:
				xml_lines.append(f'      <p begin="{p_begin}" end="{p_end}">{"".join(span_parts)}</p>')
			else:
				content_str = format_ruby_spans(clean_text) if use_ruby else escape_xml(clean_text)
				xml_lines.append(f'      <p begin="{p_begin}" end="{p_end}">{content_str}</p>')
		else:
			content_str = format_ruby_spans(clean_text) if use_ruby else escape_xml(clean_text)
			xml_lines.append(f'      <p begin="{p_begin}" end="{p_end}">{content_str}</p>')

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
	lang: str | None = None,
	ruby: str | bool | None = None,
) -> Path:
	"""Read alignment JSON file, convert to Apple Music TTML, and write to output_path."""
	if output_path is None:
		output_path = input_path.with_suffix(".ttml")
	raw = json.loads(input_path.read_text(encoding="utf-8"))
	content = alignment_to_ttml(raw, title=title, artist=artist, lang=lang, ruby=ruby)
	output_path.parent.mkdir(parents=True, exist_ok=True)
	output_path.write_text(content, encoding="utf-8")
	return output_path


def ass_text_to_ttml(
	ass_text: str,
	title: str = "",
	artist: str = "",
	lang: str | None = None,
	ruby: str | bool | None = None,
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

	# If lang is not provided, detect from the ass text or lines_data
	resolved_lang = lang if lang else detect_lyric_lang({"lines": lines_data})
	return alignment_to_ttml(
		{"lines": lines_data}, title=title, artist=artist, lang=resolved_lang, ruby=ruby
	)


def build_lyrics_bundle_zip(alignment: Any, title: str = "", artist: str = "") -> bytes:
	"""Package all common lyric formats (TTML zh-Hans/zh-Hant/Ruby and LRC Standard/zh-Hant/Pinyin) into a zip bundle."""
	import io
	import zipfile
	from src.ass2lrc import alignment_to_lrc

	buf = io.BytesIO()
	clean_name = sanitize_download_filename(title or "lyrics")
	with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
		# 1. Apple Music TTML Auto-detected
		zf.writestr(
			f"{clean_name}_AppleMusic_Auto.ttml",
			alignment_to_ttml(alignment, title=title, artist=artist),
		)
		# 2. Apple Music TTML Simplified Chinese
		zf.writestr(
			f"{clean_name}_AppleMusic_zh-Hans.ttml",
			alignment_to_ttml(alignment, title=title, artist=artist, lang="zh-Hans"),
		)
		# 3. Apple Music TTML Traditional Chinese
		zf.writestr(
			f"{clean_name}_AppleMusic_zh-Hant.ttml",
			alignment_to_ttml(alignment, title=title, artist=artist, lang="zh-Hant"),
		)
		# 4. Apple Music TTML Ruby Pinyin
		zf.writestr(
			f"{clean_name}_AppleMusic_PinyinRuby.ttml",
			alignment_to_ttml(alignment, title=title, artist=artist, ruby="pinyin"),
		)
		# 5. Standard LRC
		zf.writestr(
			f"{clean_name}_Standard.lrc",
			alignment_to_lrc(alignment, title=title, artist=artist),
		)
		# 6. Traditional LRC
		zf.writestr(
			f"{clean_name}_zh-Hant.lrc",
			alignment_to_lrc(alignment, title=title, artist=artist, lang="zh-Hant"),
		)
		# 7. Dual-line Pinyin LRC
		zf.writestr(
			f"{clean_name}_Pinyin_DualLine.lrc",
			alignment_to_lrc(alignment, title=title, artist=artist, pinyin=True),
		)

	return buf.getvalue()


def main() -> int:
	parser = argparse.ArgumentParser(description="Convert alignment JSON or ASS to Apple Music TTML")
	parser.add_argument("input", type=Path, help="Input alignment.json or subtitles.ass file")
	parser.add_argument("-o", "--output", type=Path, default=None, help="Output .ttml file")
	parser.add_argument("--title", type=str, default="", help="Song title for TTML metadata")
	parser.add_argument("--artist", type=str, default="", help="Artist name for TTML metadata")
	parser.add_argument(
		"--lang",
		type=str,
		default=None,
		help="Language code (e.g. zh-Hans, zh-Hant, en). If omitted, automatically detected from lyrics.",
	)
	parser.add_argument(
		"--ruby",
		type=str,
		default=None,
		choices=["pinyin"],
		help="Generate W3C TTML ruby phonetic annotations (e.g. pinyin).",
	)
	args = parser.parse_args()

	in_file: Path = args.input
	if not in_file.exists():
		print(f"Error: input file {in_file} does not exist.")
		return 1

	if in_file.suffix.lower() == ".json":
		out_file = convert_alignment_to_ttml(
			in_file,
			args.output,
			title=args.title,
			artist=args.artist,
			lang=args.lang,
			ruby=args.ruby,
		)
	elif in_file.suffix.lower() == ".ass":
		out_file = args.output or in_file.with_suffix(".ttml")
		ttml_text = ass_text_to_ttml(
			in_file.read_text(encoding="utf-8-sig"),
			title=args.title,
			artist=args.artist,
			lang=args.lang,
			ruby=args.ruby,
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
