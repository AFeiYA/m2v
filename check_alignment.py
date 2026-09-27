import json

# Whisper raw segments
print("=== Whisper Raw Segments ===")
with open("input/害怕的人_whisper_segments.json", "r", encoding="utf-8") as f:
    segs = json.load(f)
for i, s in enumerate(segs):
    dur = s["end"] - s["start"]
    print(f"S{i+1:2d} [{s['start']:7.2f}~{s['end']:7.2f}] ({dur:5.1f}s) {s['text'][:50]}")

print()

# Alignment result
print("=== Aligned Lines ===")
with open("output/害怕的人_alignment.json", "r", encoding="utf-8") as f:
    d = json.load(f)
for i, line in enumerate(d["lines"]):
    s = line["start"]
    e = line["end"]
    dur = e - s
    n = len(line["words"])
    text = line["text"]
    print(f"L{i+1:2d} [{s:7.2f} ~ {e:7.2f}] ({dur:5.1f}s) {n:2d}字  {text}")
