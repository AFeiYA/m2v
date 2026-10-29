const { test } = require("node:test");
const assert = require("node:assert/strict");

// Load module from lyric_editor
const { syncSyllablesOnWordChange } = require("../local/lyric_editor.js");

test("syncSyllablesOnWordChange safely ignores single-syllable or non-syllable words", () => {
  const w1 = { word: "love", start: 1.0, end: 1.5 };
  syncSyllablesOnWordChange(w1, "end");
  assert.equal(w1.syllables, undefined);

  const w2 = { word: "cat", start: 1.0, end: 1.5, syllables: [{ text: "cat", start: 1.0, end: 1.5 }] };
  w2.end = 2.0;
  syncSyllablesOnWordChange(w2, "end");
  assert.equal(w2.syllables.length, 1);
});

test("Rule 1: Word end elongation (melisma) anchors head/body and extends only the last syllable", () => {
  const w = {
    word: "never",
    start: 1.0,
    end: 1.6,
    syllables: [
      { text: "ne", start: 1.0, end: 1.25 },
      { text: "ver", start: 1.25, end: 1.6 },
    ],
  };

  // Singer elongates "never" from 1.6s to 2.4s (held note on "ver")
  w.end = 2.4;
  syncSyllablesOnWordChange(w, "end");

  // First syllable remains anchored at 1.0 -> 1.25
  assert.equal(w.syllables[0].start, 1.0);
  assert.equal(w.syllables[0].end, 1.25);

  // Second syllable absorbs extension up to 2.4
  assert.equal(w.syllables[1].start, 1.25);
  assert.equal(w.syllables[1].end, 2.4);
});

test("Rule 1: 3-syllable word end elongation preserves earlier syllables", () => {
  const w = {
    word: "momentum",
    start: 2.0,
    end: 3.0,
    syllables: [
      { text: "mo", start: 2.0, end: 2.25 },
      { text: "men", start: 2.25, end: 2.6 },
      { text: "tum", start: 2.6, end: 3.0 },
    ],
  };

  w.end = 3.8;
  syncSyllablesOnWordChange(w, "end");

  assert.equal(w.syllables[0].start, 2.0);
  assert.equal(w.syllables[0].end, 2.25);
  assert.equal(w.syllables[1].start, 2.25);
  assert.equal(w.syllables[1].end, 2.6);
  assert.equal(w.syllables[2].start, 2.6);
  assert.equal(w.syllables[2].end, 3.8);
});

test("Rule 1: Moderate word end shrinkage reduces only the last syllable", () => {
  const w = {
    word: "never",
    start: 1.0,
    end: 1.8,
    syllables: [
      { text: "ne", start: 1.0, end: 1.3 },
      { text: "ver", start: 1.3, end: 1.8 },
    ],
  };

  // Tail shrunk from 1.8 to 1.45 (still > 1.3 + 0.035)
  w.end = 1.45;
  syncSyllablesOnWordChange(w, "end");

  assert.equal(w.syllables[0].start, 1.0);
  assert.equal(w.syllables[0].end, 1.3);
  assert.equal(w.syllables[1].start, 1.3);
  assert.equal(w.syllables[1].end, 1.45);
});

test("Rule 2: Word start drag anchors tail syllables and extends/shrinks first syllable", () => {
  const w = {
    word: "forever",
    start: 2.0,
    end: 3.0,
    syllables: [
      { text: "for", start: 2.0, end: 2.3 },
      { text: "ev", start: 2.3, end: 2.6 },
      { text: "er", start: 2.6, end: 3.0 },
    ],
  };

  // Singer starts earlier at 1.7
  w.start = 1.7;
  syncSyllablesOnWordChange(w, "start");

  assert.equal(w.syllables[0].start, 1.7);
  assert.equal(w.syllables[0].end, 2.3);
  assert.equal(w.syllables[1].start, 2.3);
  assert.equal(w.syllables[1].end, 2.6);
  assert.equal(w.syllables[2].start, 2.6);
  assert.equal(w.syllables[2].end, 3.0);
});

test("Rule 3: Word nudge shifts all syllables uniformly by delta", () => {
  const w = {
    word: "running",
    start: 1.0,
    end: 1.6,
    syllables: [
      { text: "run", start: 1.0, end: 1.3 },
      { text: "ning", start: 1.3, end: 1.6 },
    ],
  };

  const delta = 0.25;
  w.start = Math.round((w.start + delta) * 1000) / 1000;
  w.end = Math.round((w.end + delta) * 1000) / 1000;
  syncSyllablesOnWordChange(w, "shift", { delta });

  assert.equal(w.syllables[0].start, 1.25);
  assert.equal(w.syllables[0].end, 1.55);
  assert.equal(w.syllables[1].start, 1.55);
  assert.equal(w.syllables[1].end, 1.85);
});

test("Rule 4: Severe compression falls back to proportional scaling with min duration clamp", () => {
  const w = {
    word: "beautiful",
    start: 1.0,
    end: 2.0,
    syllables: [
      { text: "beau", start: 1.0, end: 1.4 },
      { text: "ti", start: 1.4, end: 1.7 },
      { text: "ful", start: 1.7, end: 2.0 },
    ],
  };

  // Word compressed to just 0.18s
  w.end = 1.18;
  syncSyllablesOnWordChange(w, "end");

  // Bounds chained and strictly inside [1.0, 1.18]
  assert.equal(w.syllables[0].start, 1.0);
  assert.equal(w.syllables[2].end, 1.18);
  assert.equal(w.syllables[0].end, w.syllables[1].start);
  assert.equal(w.syllables[1].end, w.syllables[2].start);

  // Each syllable has positive duration >= minSylDur
  for (const s of w.syllables) {
    assert.ok(s.end > s.start, `syllable ${s.text} must have end > start`);
  }
});
