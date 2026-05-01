'use client';
import React, { useEffect, useRef, useState, useCallback } from 'react';

// ─── Icon paths — all 4 corners fire at once, building is one stroke ──────
// viewBox="0 0 48 48"
const ICON_PATHS = [
  // All 4 frame corners snap simultaneously
  { id:'c-tl', d:'M2,9 V2 H9',     delay:0,    dur:0.13 },
  { id:'c-tr', d:'M39,2 H46 V9',   delay:0,    dur:0.13 },
  { id:'c-bl', d:'M2,39 V46 H9',   delay:0,    dur:0.13 },
  { id:'c-br', d:'M39,46 H46 V39', delay:0,    dur:0.13 },
  // Ground sweeps (overlaps corners)
  { id:'gnd',  d:'M7,42 H41',      delay:0.10, dur:0.18 },
  // Building as ONE continuous stroke: up left wall → peak → down right wall
  { id:'bld',  d:'M11,42 V26 L24,14 L37,26 V42', delay:0.22, dur:0.38 },
  // Floor separator
  { id:'fl',   d:'M11,34 H37',     delay:0.55, dur:0.13 },
  // Windows pop in together
  { id:'w1',   d:'M14,18 h5 v5 h-5 Z', delay:0.64, dur:0.14 },
  { id:'w2',   d:'M29,18 h5 v5 h-5 Z', delay:0.68, dur:0.14 },
  // Door
  { id:'dr',   d:'M20,42 V36 Q24,31 28,36 V42', delay:0.72, dur:0.15 },
  // Compass circle
  { id:'ci',   d:'M3,15 a6,6 0 1 1 12,0 a6,6 0 1 1 -12,0', delay:0.82, dur:0.22 },
  { id:'cx',   d:'M3,15 H15 M9,9 V21', delay:0.96, dur:0.11 },
];

const LAST_PATH_END = Math.max(...ICON_PATHS.map(p => p.delay + p.dur)); // ~1.07s

// ─── Lightbulb SVG ────────────────────────────────────────────────────────
function Bulb({ em, color, state }: {
  em: number;
  color: string;
  state: 'off' | 'flicker' | 'on';
}) {
  const on = state === 'on';
  const flicker = state === 'flicker';

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', position: 'relative' }}>
      <svg
        width={em * 0.65}
        height={em}
        viewBox="0 0 13 19"
        fill="none"
        stroke={color}
        strokeWidth={1.25}
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{
          verticalAlign: 'middle',
          marginBottom: em * 0.06,
          filter: on
            ? `drop-shadow(0 0 ${em * 0.18}px ${color}dd) drop-shadow(0 0 ${em * 0.35}px ${color}66)`
            : flicker
              ? `drop-shadow(0 0 ${em * 0.08}px ${color}88)`
              : 'none',
          animation: flicker ? 'bulbFlicker .55s steps(1,end) forwards' : 'none',
          transition: on ? 'filter .3s ease' : 'none',
        }}
      >
        {/* Glass bulb */}
        <path d="M4 11.5 Q1.5 9.5 1.5 6.5 a5 5 0 0 1 10 0 Q11.5 9.5 9 11.5 Z" />
        {/* Base */}
        <path d="M4 11.5 h5" />
        <path d="M4.5 13.5 h4" />
        <path d="M5.5 15.5 h2" />
        {/* Filament — only visible when on */}
        <path
          d="M4.5 9 L6.5 7 L8.5 9"
          strokeWidth={on ? 1 : 0.4}
          opacity={on ? 1 : 0.25}
          style={{ transition: 'stroke-width .2s, opacity .2s' }}
        />
        {/* Rays — spread out when on */}
        {['on','flicker'].includes(state) && (<>
          <path d="M6.5 0.5 V-0.5"    strokeWidth={0.9} style={{ animation: on ? 'raySpread .4s ease forwards' : 'none', transformOrigin:'6.5px 6.5px' }} opacity={on ? 0.7 : 0.3} />
          <path d="M10.5 2 l.8-.8"    strokeWidth={0.9} opacity={on ? 0.7 : 0.3} style={{ animation: on ? 'raySpread .4s .04s ease forwards' : 'none', transformOrigin:'6.5px 6.5px' }} />
          <path d="M2.5 2 l-.8-.8"    strokeWidth={0.9} opacity={on ? 0.7 : 0.3} style={{ animation: on ? 'raySpread .4s .08s ease forwards' : 'none', transformOrigin:'6.5px 6.5px' }} />
          <path d="M12.5 6.5 H13.5"   strokeWidth={0.9} opacity={on ? 0.7 : 0.3} style={{ animation: on ? 'raySpread .4s .12s ease forwards' : 'none', transformOrigin:'6.5px 6.5px' }} />
          <path d="M-0.5 6.5 H0.5"    strokeWidth={0.9} opacity={on ? 0.7 : 0.3} style={{ animation: on ? 'raySpread .4s .16s ease forwards' : 'none', transformOrigin:'6.5px 6.5px' }} />
        </>)}
      </svg>
    </span>
  );
}

// ─── Wordmark letters — light spreads from the bulb outward ───────────────
const WORD_BEFORE = ['P','E','T','R','O','N']; // indices 0-5
const WORD_AFTER  = ['S'];                      // index 0 after bulb

function WordLetter({ char, distFromBulb, lit }: {
  char: string; distFromBulb: number; lit: boolean;
}) {
  const delay = distFromBulb * 0.07; // seconds, closer = sooner
  return (
    <span style={{
      opacity: lit ? 1 : 0.08,
      transition: lit ? `opacity .35s ease ${delay}s` : 'none',
    }}>{char}</span>
  );
}

// ─── Main component ───────────────────────────────────────────────────────
interface Props {
  height?: number;
  color?: string;
  animated?: boolean;
  iconOnly?: boolean;
  style?: React.CSSProperties;
}

export default function PetronusLogo({
  height = 32,
  color = '#c4a882',
  animated = false,
  iconOnly = false,
  style,
}: Props) {
  const pathRefs = useRef<(SVGPathElement | null)[]>([]);
  const [built, setBuilt] = useState(!animated);
  const [bulbState, setBulbState] = useState<'off'|'flicker'|'on'>(animated ? 'off' : 'on');

  const runAnimation = useCallback(() => {
    setBuilt(false);
    setBulbState('off');

    // Reset all paths
    pathRefs.current.forEach(el => {
      if (!el) return;
      const len = el.getTotalLength();
      el.style.transition = 'none';
      el.style.strokeDasharray = `${len}`;
      el.style.strokeDashoffset = `${len}`;
    });

    requestAnimationFrame(() => requestAnimationFrame(() => {
      // Animate each path
      ICON_PATHS.forEach((p, i) => {
        const el = pathRefs.current[i];
        if (!el) return;
        el.style.transition = `stroke-dashoffset ${p.dur}s cubic-bezier(0.4,0,0.2,1) ${p.delay}s`;
        el.style.strokeDashoffset = '0';
      });

      // After construction: flicker bulb, then fully on
      setTimeout(() => setBulbState('flicker'), LAST_PATH_END * 1000 + 60);
      setTimeout(() => { setBulbState('on'); setBuilt(true); }, LAST_PATH_END * 1000 + 680);
    }));
  }, []);

  useEffect(() => {
    if (animated) runAnimation();
  }, [animated, runAnimation]);

  const iconPx   = height * 1.55;
  const fontSize = height * 0.88;

  return (
    <div
      style={{ display: 'inline-flex', alignItems: 'center', gap: height * 0.32, ...style }}
      onDoubleClick={() => animated && runAnimation()}
    >
      {/* Icon */}
      <svg
        width={iconPx} height={iconPx}
        viewBox="0 0 48 48"
        fill="none" stroke={color}
        strokeWidth={1.3} strokeLinecap="round" strokeLinejoin="round"
        style={{
          flexShrink: 0,
          filter: built
            ? `drop-shadow(0 0 5px ${color}66) drop-shadow(0 0 12px ${color}33)`
            : 'none',
          transition: 'filter .5s ease',
        }}
      >
        {ICON_PATHS.map((p, i) => (
          <path
            key={p.id} d={p.d}
            ref={el => { pathRefs.current[i] = el; }}
          />
        ))}
      </svg>

      {/* Wordmark */}
      {!iconOnly && (
        <div style={{
          display: 'inline-flex', alignItems: 'center',
          fontFamily: 'Space Grotesk, sans-serif',
          fontWeight: 700, fontSize: fontSize,
          color, letterSpacing: '0.07em', lineHeight: 1,
          userSelect: 'none',
        }}>
          {WORD_BEFORE.map((ch, i) => (
            <WordLetter key={ch+i} char={ch} distFromBulb={WORD_BEFORE.length - i} lit={built} />
          ))}
          <Bulb em={fontSize} color={color} state={bulbState} />
          {WORD_AFTER.map((ch, i) => (
            <WordLetter key={ch+i} char={ch} distFromBulb={i + 1} lit={built} />
          ))}
        </div>
      )}
    </div>
  );
}
