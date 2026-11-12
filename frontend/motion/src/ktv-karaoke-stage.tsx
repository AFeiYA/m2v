import React from 'react';
import type { Project, Line, Word, Options } from './model';
import type { StreamPalette } from './stream-layout';

export interface SlotState {
  line: Line;
  lineIndex: number;
  isSinging: boolean;
  isUpcoming: boolean;
  isPast: boolean;
  opacity: number;
  timeUntilStart: number;
}

export const BOKEH_LIGHTS = [
  { x: 220, y: 180, size: 140, color: 'rgba(220, 38, 38, 0.28)', pulseSpeed: 0.04 },
  { x: 1700, y: 220, size: 160, color: 'rgba(16, 185, 129, 0.24)', pulseSpeed: 0.035 },
  { x: 960, y: 240, size: 220, color: 'rgba(245, 158, 11, 0.25)', pulseSpeed: 0.05 },
  { x: 380, y: 520, size: 180, color: 'rgba(245, 158, 11, 0.22)', pulseSpeed: 0.045 },
  { x: 1540, y: 560, size: 190, color: 'rgba(220, 38, 38, 0.26)', pulseSpeed: 0.038 },
  { x: 180, y: 840, size: 150, color: 'rgba(16, 185, 129, 0.26)', pulseSpeed: 0.04 },
  { x: 1740, y: 860, size: 160, color: 'rgba(245, 158, 11, 0.28)', pulseSpeed: 0.048 },
  { x: 620, y: 150, size: 130, color: 'rgba(254, 240, 138, 0.3)', pulseSpeed: 0.055 },
  { x: 1300, y: 160, size: 130, color: 'rgba(254, 240, 138, 0.3)', pulseSpeed: 0.052 },
  { x: 820, y: 780, size: 170, color: 'rgba(220, 38, 38, 0.22)', pulseSpeed: 0.042 },
  { x: 1100, y: 800, size: 170, color: 'rgba(16, 185, 129, 0.24)', pulseSpeed: 0.046 },
];

export const SNOW_FLAKES = Array.from({ length: 75 }, (_, i) => ({
  id: i,
  x: (i * 179) % 1920,
  speed: 1.0 + ((i * 31) % 25) / 10,
  size: 2.2 + ((i * 17) % 6),
  swayAmp: 16 + ((i * 13) % 24),
  swaySpeed: 0.02 + ((i * 11) % 20) / 450,
  opacity: 0.35 + ((i * 23) % 55) / 100,
}));

export function getKtvSlotState(slot: 0 | 1, lines: Line[], currentTime: number): SlotState | null {
  const candidates: Array<{ line: Line; index: number }> = [];
  for (let i = 0; i < lines.length; i++) {
    if (i % 2 === slot) {
      candidates.push({ line: lines[i], index: i });
    }
  }

  for (let k = 0; k < candidates.length; k++) {
    const { line, index } = candidates[k];
    const prev = k > 0 ? candidates[k - 1].line : null;

    let appearTime = 0;
    if (prev) {
      const gap = line.start - prev.end;
      if (gap > 4.0) {
        appearTime = line.start - 2.8;
      } else {
        appearTime = prev.end + 0.25;
      }
    } else {
      appearTime = 0.0;
    }

    const leaveTime = line.end + 0.45;

    if (currentTime >= appearTime && currentTime <= leaveTime) {
      const isSinging = currentTime >= line.start && currentTime <= line.end;
      const isUpcoming = currentTime < line.start;
      const isPast = currentTime > line.end;
      const fadeIn = Math.min(1.0, Math.max(0.0, (currentTime - appearTime) / 0.35));
      const timeUntilStart = Math.max(0, line.start - currentTime);

      return {
        line,
        lineIndex: index,
        isSinging,
        isUpcoming,
        isPast,
        opacity: fadeIn,
        timeUntilStart,
      };
    }
  }

  return null;
}

export function getLineWords(line: Line): Word[] {
  if (line.words && line.words.length > 0) {
    return line.words;
  }
  const tokens = line.text.split(/(\s+)/).filter(Boolean);
  const dur = Math.max(0.1, line.end - line.start);
  const step = dur / Math.max(1, tokens.length);
  return tokens.map((w, idx) => ({
    word: w,
    start: line.start + idx * step,
    end: line.start + (idx + 1) * step,
  }));
}

export const KtvKaraokeStage: React.FC<{
  project: Project;
  options?: Options;
  t: number;
  frame: number;
  width: number;
  height: number;
  palette?: StreamPalette;
}> = ({ project, options, t, frame, width, height, palette }) => {
  const isLandscape = width >= height;
  const lines = project.lines || [];
  const currentTime = t;

  // Track & Theme Detection
  const rawTitle = project.title || project.song_identity?.title || 'Untitled Track';
  const displayTitle = rawTitle.replace(/[-_]/g, ' ').toUpperCase();
  const displayArtist = project.artist || project.song_identity?.artist || '';
  const tempoBpm = Math.round(project.features?.tempo || project.analysis?.bpm || (project as any).bpm || 0);

  const preset = options?.preset || project.song_identity?.visual_theme || '';
  const isChristmas =
    preset === 'christmas2026' ||
    preset === 'christmas_special' ||
    project.song_identity?.visual_theme === 'christmas2026' ||
    project.song_identity?.visual_theme === 'christmas_special';

  const accent = isChristmas ? '#FFD700' : (palette?.accent || '#b7f34a');
  const sungHighlight = isChristmas ? '#FEF08A' : accent;

  // Section Marker Calculation
  let currentSection = 'Intro';
  if (project.sections && project.sections.length > 0) {
    for (const s of project.sections) {
      if (currentTime >= s.start - 0.2) {
        currentSection = s.name.replace(/^\[|\]$/g, '').trim();
      }
    }
  } else {
    const activeLine = lines.find(l => currentTime >= l.start - 0.5 && currentTime <= l.end + 0.5);
    if (activeLine?.section) {
      currentSection = activeLine.section.replace(/^\[|\]$/g, '').trim();
    }
  }

  const sLower = currentSection.toLowerCase();
  const isChorus = sLower.includes('chorus') || currentSection.includes('副歌');
  const isInterlude = sLower.includes('interlude') || sLower.includes('solo') || currentSection.includes('间奏');
  const isVerse = sLower.includes('verse') || currentSection.includes('主歌');

  const sectionIcon = isChristmas
    ? (isChorus ? '🔔' : isInterlude ? '🛷' : '🎄')
    : (isChorus ? '🎵' : isInterlude ? '⚡' : isVerse ? '🎤' : '✨');

  // Compute Dual Slots
  const slotTop = getKtvSlotState(0, lines, currentTime);
  const slotBottom = getKtvSlotState(1, lines, currentTime);
  const isInstrumental = slotTop === null && slotBottom === null;

  const totalDuration = project.duration || lines.at(-1)?.end || 180;
  const progressPercent = Math.min(100, (currentTime / Math.max(1, totalDuration)) * 100);

  // Card Font Scaling
  const cardFontSize = isLandscape
    ? Math.max(30, Math.round(width * 0.024))
    : Math.max(22, Math.round(width * 0.055));

  // Render individual KTV line card with word-by-word zoom & lead-in countdown
  const renderLineCard = (slotState: SlotState, slotType: 'top' | 'bottom') => {
    const { line, isSinging, isUpcoming, isPast, opacity, timeUntilStart } = slotState;
    const isTop = slotType === 'top';
    const words = getLineWords(line);

    // 4-beat rhythm countdown indicator when within 2.0s of singing
    const showLeadIn = isUpcoming && timeUntilStart <= 2.0 && timeUntilStart > 0;
    const activeBeat = showLeadIn ? Math.floor((2.0 - timeUntilStart) / 0.5) + 1 : 0;

    return (
      <div
        key={`${slotType}-${slotState.lineIndex}`}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: isLandscape ? (isTop ? 'flex-start' : 'flex-end') : 'center',
          width: '100%',
          paddingLeft: isLandscape && isTop ? '60px' : '0px',
          paddingRight: isLandscape && !isTop ? '60px' : '0px',
          opacity,
          transform: `translateY(${Math.round((1 - opacity) * 8)}px)`,
          transition: 'opacity 0.25s ease-out, transform 0.25s ease-out',
        }}
      >
        <div
          style={{
            display: 'inline-flex',
            flexWrap: 'wrap',
            alignItems: 'center',
            columnGap: isLandscape ? '16px' : '10px',
            rowGap: '8px',
            maxWidth: isLandscape ? `${Math.round(width * 0.85)}px` : `${Math.round(width * 0.92)}px`,
            padding: isLandscape ? '16px 36px' : '12px 20px',
            borderRadius: isLandscape ? '24px' : '18px',
            backgroundColor: isChristmas
              ? (isSinging ? 'rgba(42, 5, 5, 0.88)' : isUpcoming ? 'rgba(22, 3, 3, 0.68)' : 'rgba(18, 2, 2, 0.52)')
              : (isSinging ? 'rgba(12, 18, 28, 0.85)' : isUpcoming ? 'rgba(8, 12, 20, 0.72)' : 'rgba(6, 10, 16, 0.55)'),
            border: isChristmas
              ? (isSinging ? '2px solid #F59E0B' : isUpcoming ? '1.5px solid rgba(245, 158, 11, 0.35)' : '1px solid rgba(245, 158, 11, 0.15)')
              : (isSinging ? `2px solid ${accent}` : isUpcoming ? '1.5px solid rgba(255, 255, 255, 0.18)' : '1px solid rgba(255, 255, 255, 0.08)'),
            backdropFilter: 'blur(14px)',
            WebkitBackdropFilter: 'blur(14px)',
            boxShadow: isSinging
              ? (isChristmas
                  ? '0 0 28px rgba(245, 158, 11, 0.45), 0 16px 40px rgba(0, 0, 0, 0.8)'
                  : `0 0 28px ${accent}55, 0 16px 40px rgba(0, 0, 0, 0.8)`)
              : '0 8px 24px rgba(0, 0, 0, 0.6)',
            transition: 'all 0.2s ease-out',
          }}
        >
          {/* Head Indicator: Animated Singing Cue / 4-Beat Countdown */}
          <div
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              marginRight: '8px',
              fontSize: isLandscape ? '24px' : '18px',
              userSelect: 'none',
            }}
          >
            {isSinging ? (
              <span
                style={{
                  display: 'inline-block',
                  transform: `scale(${1 + Math.sin(frame * 0.3) * 0.15}) rotate(${Math.sin(frame * 0.2) * 8}deg)`,
                  filter: `drop-shadow(0 0 8px ${accent})`,
                }}
              >
                {isChristmas ? '🔔' : '🎤'}
              </span>
            ) : showLeadIn ? (
              <div style={{ display: 'inline-flex', gap: '6px', alignItems: 'center' }}>
                {[1, 2, 3, 4].map((b) => (
                  <span
                    key={b}
                    style={{
                      display: 'inline-block',
                      width: isLandscape ? '12px' : '9px',
                      height: isLandscape ? '12px' : '9px',
                      borderRadius: '50%',
                      backgroundColor: b <= activeBeat ? accent : 'rgba(255, 255, 255, 0.25)',
                      boxShadow: b <= activeBeat ? `0 0 10px ${accent}, 0 0 16px ${sungHighlight}` : 'none',
                      transform: b === activeBeat ? 'scale(1.4)' : 'scale(1.0)',
                      transition: 'all 0.08s ease-out',
                    }}
                  />
                ))}
              </div>
            ) : (
              <span
                style={{
                  fontSize: isLandscape ? '16px' : '13px',
                  color: isPast ? `${accent}55` : `${accent}99`,
                  fontWeight: 700,
                }}
              >
                {isTop ? '▲' : '▼'}
              </span>
            )}
          </div>

          {/* Word-by-word Syllables with Active Zoom (scale 1.12) & Brilliant Highlight */}
          {words.map((wordObj, wIdx) => {
            const isWordPast = currentTime >= wordObj.end;
            const isWordActive = currentTime >= wordObj.start && currentTime < wordObj.end;

            let wordProgress = 0;
            if (isWordPast) wordProgress = 1;
            else if (isWordActive) {
              wordProgress = (currentTime - wordObj.start) / Math.max(0.01, wordObj.end - wordObj.start);
            }

            return (
              <span
                key={wIdx}
                style={{
                  display: 'inline-block',
                  fontSize: `${cardFontSize}px`,
                  fontWeight: 900,
                  letterSpacing: '0.5px',
                  position: 'relative',
                  transform: isWordActive ? 'scale(1.12)' : 'scale(1.0)',
                  transition: 'transform 0.08s ease-out',
                  lineHeight: '1.25',
                }}
              >
                {/* Unsung Base Layer: NEVER black! Crisp pure white with dark drop-shadow */}
                <span
                  style={{
                    color: isWordPast
                      ? (isChristmas ? '#FDE047' : accent)
                      : isSinging
                      ? 'rgba(255, 255, 255, 0.78)'
                      : '#FFFFFF',
                    textShadow: isWordPast
                      ? `0 0 16px ${accent}`
                      : '0 2px 8px rgba(0,0,0,0.95), 0 0 4px rgba(0,0,0,0.8)',
                  }}
                >
                  {wordObj.word}
                </span>

                {/* Active Singing Layer with Holiday/Accent Bloom */}
                {isWordActive && (
                  <span
                    style={{
                      position: 'absolute',
                      left: 0,
                      top: 0,
                      color: sungHighlight,
                      textShadow: isChristmas
                        ? '0 0 20px #F59E0B, 0 0 38px #FBBF24, 0 0 60px rgba(220, 38, 38, 0.7)'
                        : `0 0 18px ${accent}, 0 0 32px ${accent}`,
                      overflow: 'hidden',
                      width: `${Math.round(wordProgress * 100)}%`,
                      whiteSpace: 'nowrap',
                      pointerEvents: 'none',
                    }}
                  >
                    {wordObj.word}
                  </span>
                )}
              </span>
            );
          })}
        </div>
      </div>
    );
  };

  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        backgroundColor: isChristmas ? '#120303' : (palette?.background || '#090d14'),
        backgroundImage: isChristmas
          ? 'radial-gradient(circle at 50% 28%, #3d0707 0%, #260404 42%, #140202 78%, #080101 100%)'
          : `radial-gradient(circle at 50% 30%, rgba(18, 26, 40, 0.75) 0%, rgba(6, 10, 16, 0.96) 100%)`,
        color: '#FFFFFF',
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif",
        overflow: 'hidden',
      }}
    >
      {/* Universal Ambient Blurred Cover Backdrop (for non-Christmas tracks) */}
      {!isChristmas && project.song_cover && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            backgroundImage: `url(${project.song_cover})`,
            backgroundSize: 'cover',
            backgroundPosition: 'center',
            filter: 'blur(32px) brightness(0.38)',
            transform: 'scale(1.1)',
            pointerEvents: 'none',
          }}
        />
      )}

      {/* 1. Warm Bokeh Fairy Lights (Christmas Special Only) */}
      {isChristmas && BOKEH_LIGHTS.map((orb, i) => {
        const pulse = 0.82 + Math.sin(frame * orb.pulseSpeed + i) * 0.18;
        return (
          <div
            key={i}
            style={{
              position: 'absolute',
              left: `${(orb.x / 1920) * width}px`,
              top: `${(orb.y / 1080) * height}px`,
              width: `${(orb.size / 1920) * width}px`,
              height: `${(orb.size / 1920) * width}px`,
              borderRadius: '50%',
              backgroundColor: orb.color,
              filter: `blur(${orb.size * 0.35}px)`,
              transform: `translate(-50%, -50%) scale(${pulse})`,
              pointerEvents: 'none',
            }}
          />
        );
      })}

      {/* 2. Gentle Festive Snow Particles (Christmas Special Only) */}
      {isChristmas && SNOW_FLAKES.map((flake) => {
        const yOffset = ((frame * flake.speed * 2.2 + flake.id * 73) % (height + 60)) - 30;
        const xOffset = flake.x + Math.sin(frame * flake.swaySpeed + flake.id) * flake.swayAmp;
        return (
          <div
            key={flake.id}
            style={{
              position: 'absolute',
              left: `${(xOffset / 1920) * width}px`,
              top: `${yOffset}px`,
              width: `${(flake.size / 1920) * width}px`,
              height: `${(flake.size / 1920) * width}px`,
              borderRadius: '50%',
              backgroundColor: '#FFFFFF',
              opacity: flake.opacity,
              boxShadow: `0 0 6px rgba(255, 255, 255, ${flake.opacity * 0.8})`,
              pointerEvents: 'none',
            }}
          />
        );
      })}

      {/* 3. Victorian Ornate Gold Double Frame (Christmas Special Only in 16:9) */}
      {isChristmas && isLandscape && (
        <div
          style={{
            position: 'absolute',
            inset: '24px',
            border: '2px solid rgba(245, 158, 11, 0.5)',
            borderRadius: '16px',
            pointerEvents: 'none',
            boxShadow: 'inset 0 0 30px rgba(245, 158, 11, 0.1)',
          }}
        >
          {/* Inner Dotted Filigree Border */}
          <div
            style={{
              position: 'absolute',
              inset: '8px',
              border: '1.5px dashed rgba(245, 158, 11, 0.3)',
              borderRadius: '10px',
            }}
          />
          {/* Corner Festive Ornaments */}
          <span style={{ position: 'absolute', top: '10px', left: '14px', fontSize: '22px' }}>🎄</span>
          <span style={{ position: 'absolute', top: '10px', right: '14px', fontSize: '22px' }}>🎄</span>
          <span style={{ position: 'absolute', bottom: '10px', left: '14px', fontSize: '22px' }}>❄️</span>
          <span style={{ position: 'absolute', bottom: '10px', right: '14px', fontSize: '22px' }}>❄️</span>
        </div>
      )}

      {/* 4. Top Header HUD */}
      <div
        style={{
          position: 'absolute',
          top: isLandscape ? '44px' : '28px',
          left: 0,
          right: 0,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          pointerEvents: 'none',
          zIndex: 10,
        }}
      >
        {/* Section Ribbon Badge */}
        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
            padding: isLandscape ? '6px 20px' : '4px 14px',
            borderRadius: '999px',
            background: isChristmas ? 'rgba(20, 20, 20, 0.72)' : 'rgba(12, 18, 28, 0.75)',
            border: `1.5px solid ${isChristmas ? '#F59E0B' : accent}`,
            boxShadow: `0 0 16px ${isChristmas ? 'rgba(245, 158, 11, 0.4)' : accent + '44'}`,
            marginBottom: isLandscape ? '10px' : '6px',
          }}
        >
          <span style={{ fontSize: isLandscape ? '18px' : '14px' }}>{sectionIcon}</span>
          <span
            style={{
              fontSize: isLandscape ? '16px' : '13px',
              fontWeight: 800,
              letterSpacing: '2.5px',
              textTransform: 'uppercase',
              color: isChristmas ? '#FEF08A' : accent,
              textShadow: '0 1px 3px rgba(0,0,0,0.8)',
            }}
          >
            {currentSection}
          </span>
        </div>

        {/* Title */}
        <h1
          style={{
            margin: '0 0 4px 0',
            fontSize: isLandscape ? '34px' : '22px',
            fontWeight: 900,
            letterSpacing: '1px',
            color: isChristmas ? '#FEF08A' : '#FFFFFF',
            textShadow: isChristmas
              ? '0 2px 8px rgba(0,0,0,0.8), 0 0 20px rgba(245, 158, 11, 0.4)'
              : '0 2px 8px rgba(0,0,0,0.9)',
          }}
        >
          {displayTitle}
        </h1>

        {/* Subtitle / Artist */}
        {isLandscape && (
          <p
            style={{
              margin: 0,
              fontSize: '14px',
              fontWeight: 600,
              color: isChristmas ? '#FDE68A' : 'rgba(255, 255, 255, 0.75)',
              letterSpacing: '2px',
              textShadow: '0 2px 4px rgba(0,0,0,0.8)',
            }}
          >
            {displayArtist ? `${displayArtist} • ` : ''}{tempoBpm > 0 ? `${tempoBpm} BPM` : (isChristmas ? 'VICTORIAN CHRISTMAS' : 'KARAOKE')}
          </p>
        )}
      </div>

      {/* 5. Center Stage: Dual Line Karaoke Cards or Instrumental Break */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center',
          gap: isLandscape ? '36px' : '24px',
          padding: isLandscape ? '120px 48px' : '100px 18px',
          zIndex: 5,
        }}
      >
        {isInstrumental ? (
          /* Instrumental Break Card */
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '12px',
              padding: isLandscape ? '32px 56px' : '24px 32px',
              borderRadius: isLandscape ? '28px' : '20px',
              backgroundColor: isChristmas ? 'rgba(30, 4, 4, 0.68)' : 'rgba(12, 18, 28, 0.75)',
              border: `1.5px solid ${isChristmas ? 'rgba(245, 158, 11, 0.4)' : accent + '55'}`,
              boxShadow: '0 20px 50px rgba(0, 0, 0, 0.7)',
              backdropFilter: 'blur(14px)',
            }}
          >
            <div style={{ fontSize: isLandscape ? '44px' : '32px' }}>
              {isChristmas ? '🛷 ❄️ 🔔' : '🎵 ⚡ 🎧'}
            </div>
            <div
              style={{
                fontSize: isLandscape ? '26px' : '18px',
                fontWeight: 800,
                letterSpacing: '2.5px',
                color: isChristmas ? '#FEF08A' : accent,
                textTransform: 'uppercase',
                textShadow: `0 0 20px ${isChristmas ? 'rgba(245, 158, 11, 0.6)' : accent + '66'}`,
              }}
            >
              ♫ {currentSection} ♫
            </div>
            <div
              style={{
                fontSize: isLandscape ? '15px' : '12px',
                color: '#E2E8F0',
                letterSpacing: '1.2px',
                opacity: 0.8,
              }}
            >
              {isChristmas ? 'Listen to the sleigh bells... Get ready to sing!' : 'Feel the groove... Get ready to sing!'}
            </div>
          </div>
        ) : (
          <>
            {slotTop && renderLineCard(slotTop, 'top')}
            {slotBottom && renderLineCard(slotBottom, 'bottom')}
          </>
        )}
      </div>

      {/* 6. Bottom Timeline HUD */}
      <div
        style={{
          position: 'absolute',
          bottom: isLandscape ? '44px' : '24px',
          left: isLandscape ? '80px' : '24px',
          right: isLandscape ? '80px' : '24px',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
          zIndex: 10,
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            fontSize: isLandscape ? '14px' : '11px',
            fontWeight: 600,
            letterSpacing: '1.2px',
            color: isChristmas ? '#FDE68A' : 'rgba(255, 255, 255, 0.8)',
          }}
        >
          <span>
            {Math.floor(currentTime / 60).toString().padStart(2, '0')}:
            {Math.floor(currentTime % 60).toString().padStart(2, '0')}
          </span>
          <span
            style={{
              color: isChristmas ? '#FEF08A' : accent,
              fontWeight: 800,
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            {isChristmas && <span>🎄</span>}
            <span>{tempoBpm > 0 ? `${tempoBpm} BPM` : 'DUAL KTV'}</span>
            {isChristmas && <span>❄️</span>}
          </span>
          <span>
            {Math.floor(totalDuration / 60).toString().padStart(2, '0')}:
            {Math.floor(totalDuration % 60).toString().padStart(2, '0')}
          </span>
        </div>

        {/* Progress Bar */}
        <div
          style={{
            width: '100%',
            height: isLandscape ? '6px' : '4px',
            backgroundColor: 'rgba(255, 255, 255, 0.15)',
            borderRadius: '999px',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              width: `${progressPercent}%`,
              height: '100%',
              background: isChristmas
                ? 'linear-gradient(90deg, #DC2626 0%, #F59E0B 50%, #FEF08A 100%)'
                : `linear-gradient(90deg, ${accent}88 0%, ${accent} 100%)`,
              borderRadius: '999px',
              boxShadow: `0 0 12px ${accent}`,
              transition: 'width 0.1s linear',
            }}
          />
        </div>
      </div>
    </div>
  );
};
