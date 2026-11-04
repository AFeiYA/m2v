import { isWebCodecsSupported, exportMotionWebCodecs, type ExportRange } from './webcodecs-exporter';
import { normalizeProject, resolveVisualMode, type Project, type VisualMode } from './model';

export function resolveClipRange(
  project: Project,
  sectionName?: string,
  durationLimit?: number
): { start: number; length: number; title: string } {
  const fullDuration = project.duration || 60;
  const lines = (project.lines || []).filter(l => l.end > l.start);
  const sections = project.sections || [];

  const findSection = (pattern: RegExp) => {
    const sec = sections.find(s => pattern.test(String(s.name || '').trim().replace(/^\[|\]$/g, '')));
    if (sec) {
      const index = sections.indexOf(sec);
      const end = Number(sec.end ?? sections[index + 1]?.start ?? project.duration ?? lines.at(-1)?.end);
      const members = lines.filter(l => l.start >= sec.start - 0.05 && l.start < end);
      return {
        start: sec.start,
        end: members.length ? members.at(-1)!.end : end,
      };
    }
    const first = lines.findIndex(l => pattern.test(String(l.section || '').trim().replace(/^\[|\]$/g, '')));
    if (first < 0) return null;
    let last = first;
    while (last + 1 < lines.length && lines[last + 1].section === lines[first].section) last++;
    return { start: lines[first].start, end: lines[last].end };
  };

  const name = (sectionName || '').trim().toLowerCase();
  let clipStart = 0;
  let clipLength = durationLimit && durationLimit > 0 ? durationLimit : fullDuration;

  if (name === 'chorus') {
    const match = findSection(/^(?:(?:final\s+)?chorus(?:\s*\d+)?|副歌.*)$/i);
    if (match) {
      clipStart = match.start;
      const matchDur = match.end - match.start;
      clipLength = durationLimit && durationLimit > 0 ? durationLimit : (matchDur > 0 ? matchDur : 30);
    }
  } else if (name === 'verse1' || name === 'verse') {
    const match = findSection(/^(?:verse(?:\s*1)?|主歌(?:\s*1)?.*)$/i);
    if (match) {
      clipStart = match.start;
      const matchDur = match.end - match.start;
      clipLength = durationLimit && durationLimit > 0 ? durationLimit : (matchDur > 0 ? matchDur : 30);
    }
  } else if (name === 'intro') {
    const match = findSection(/^(?:intro|前奏.*)$/i);
    if (match) {
      clipStart = match.start;
      const matchDur = match.end - match.start;
      clipLength = durationLimit && durationLimit > 0 ? durationLimit : (matchDur > 0 ? matchDur : 30);
    }
  }

  if (clipStart >= fullDuration) clipStart = 0;
  if (clipStart + clipLength > fullDuration) {
    clipLength = Math.max(1, fullDuration - clipStart);
  }

  const title = (name && name !== 'full') ? (name.charAt(0).toUpperCase() + name.slice(1)) : 'Full song';
  return { start: clipStart, length: clipLength, title };
}

export {
  isWebCodecsSupported,
  exportMotionWebCodecs,
  normalizeProject,
  resolveVisualMode,
};
