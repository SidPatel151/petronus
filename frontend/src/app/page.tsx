'use client';
import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import PetronusLogo from '@/components/ui/PetronusLogo';

// ─── Theme context ─────────────────────────────────────────────────────────
type Theme = 'dark' | 'light';
const ThemeCtx = createContext<{ theme: Theme; toggle: () => void }>({ theme: 'dark', toggle: () => {} });
const useTheme = () => useContext(ThemeCtx);

// ─── Theme token helper ────────────────────────────────────────────────────
function tk(theme: Theme) {
  const dark = theme === 'dark';
  return {
    text:     dark ? '#f5f1ec' : '#1a1714',
    textSub:  dark ? '#c8bfb4' : '#3d3530',
    textMute: dark ? '#a09890' : '#6b5f57',
    textDim:  dark ? '#787068' : '#8c7e75',
    accent:   dark ? '#c4a882' : '#9e7a4a',
    accentAlt:dark ? '#8fa898' : '#3d6b5a',
    amber:    dark ? '#d4943a' : '#b36a10',
    border:   dark ? 'rgba(255,255,255,0.05)' : 'rgba(0,0,0,0.09)',
    borderAccent: dark ? 'rgba(196,168,130,0.2)' : 'rgba(158,122,74,0.3)',
    card:     dark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.03)',
    cardHover:dark ? 'rgba(196,168,130,0.04)' : 'rgba(158,122,74,0.06)',
    redBg:    dark ? 'rgba(180,60,60,0.03)'   : 'rgba(120,30,30,0.04)',
    redBorder:dark ? 'rgba(180,60,60,0.18)'   : 'rgba(120,30,30,0.22)',
    redText:  dark ? '#b04040' : '#8b2020',
  };
}

// ─── SVG icon set ──────────────────────────────────────────────────────────
const SZ = 22;
function Icon({ d, size = SZ, color = 'currentColor', fill = false, strokeWidth = 1.4 }: { d: string | readonly string[]; size?: number; color?: string; fill?: boolean; strokeWidth?: number }) {
  const paths = Array.isArray(d) ? d : [d];
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round">
      {paths.map((p, i) => <path key={i} d={p} fill={fill ? color : 'none'} />)}
    </svg>
  );
}

const ICONS = {
  globe:      'M12 2a10 10 0 1 0 0 20A10 10 0 0 0 12 2zm0 0c-2.8 4-4 7-4 10s1.2 6 4 10m0-20c2.8 4 4 7 4 10s-1.2 6-4 10M2 12h20',
  building:   ['M3 21h18', 'M5 21V7l7-4 7 4v14', 'M9 21v-6h6v6'],
  blueprint:  ['M2 3h20v18H2z', 'M8 3v18', 'M2 9h6', 'M2 15h6', 'M14 9l4 4-4 4', 'M12 13h6'],
  bolt:       'M13 2L3 14h9l-1 8 10-12h-9l1-8z',
  facade:     ['M3 21h18', 'M4 21V8l8-6 8 6v13', 'M9 21v-5h6v5', 'M9 10h2v3H9z', 'M13 10h2v3h-2z'],
  shield:     ['M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z', 'M9 12l2 2 4-4'],
  map_pin:    ['M21 10c0 7-9 13-9 13S3 17 3 10a9 9 0 0 1 18 0z', 'M12 7a3 3 0 1 0 0 6 3 3 0 0 0 0-6z'],
  cube:       ['M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z', 'M3.27 6.96L12 12.01l8.73-5.05', 'M12 22.08V12'],
  layers:     ['M12 2l9 4.5-9 4.5-9-4.5z', 'M3 11.5l9 4.5 9-4.5', 'M3 16l9 4.5 9-4.5'],
  mountain:   ['M3 20l5-8 4 4 3-5 6 9H3z'],
  triangle:   'M12 2L2 22h20L12 2z',
  lightning:  'M13 2L3 14h9l-1 8 10-12h-9l1-8z',
  weather:    ['M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z'],
  rocket:     ['M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z', 'M12 15l-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z', 'M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0', 'M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5'],
  check:      ['M20 6L9 17l-5-5'],
  gear:       ['M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z', 'M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z'],
  sun:        ['M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10z', 'M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42'],
  moon:       'M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z',
} as const;

// ─── Architecture hero images ──────────────────────────────────────────────
const HERO_DARK = [
  'https://images.unsplash.com/photo-1486325212027-8081e485255e?w=1920&q=75&auto=format',
  'https://images.unsplash.com/photo-1464082354059-27db6ce50048?w=1920&q=75&auto=format',
  'https://images.unsplash.com/photo-1477959858617-67f85cf4f1df?w=1920&q=75&auto=format',
  'https://images.unsplash.com/photo-1486718448742-163732cd1544?w=1920&q=75&auto=format',
];
const HERO_LIGHT = [
  'https://images.unsplash.com/photo-1512917774080-9991f1c4c750?w=1920&q=75&auto=format',
  'https://images.unsplash.com/photo-1600585154340-be6161a56a0c?w=1920&q=75&auto=format',
  'https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?w=1920&q=75&auto=format',
  'https://images.unsplash.com/photo-1580587771525-78b9dba3b914?w=1920&q=75&auto=format',
];

function ArchBackground() {
  const { theme } = useTheme();
  const imgs = theme === 'light' ? HERO_LIGHT : HERO_DARK;
  const [idx, setIdx] = useState(0);
  const [next, setNext] = useState(1);
  const [fading, setFading] = useState(false);

  // Reset index when theme flips so it starts fresh
  useEffect(() => { setIdx(0); setNext(1); }, [theme]);

  useEffect(() => {
    const id = setInterval(() => {
      setFading(true);
      setTimeout(() => {
        setIdx(i => (i + 1) % imgs.length);
        setNext(i => (i + 1) % imgs.length);
        setFading(false);
      }, 1200);
    }, 6000);
    return () => clearInterval(id);
  }, [imgs]);

  const overlay = theme === 'light'
    ? 'linear-gradient(180deg,rgba(248,246,243,0.78) 0%,rgba(248,246,243,0.62) 40%,rgba(248,246,243,0.82) 100%)'
    : 'linear-gradient(180deg,rgba(6,5,4,0.82) 0%,rgba(6,5,4,0.72) 40%,rgba(6,5,4,0.88) 100%)';
  const vignette = theme === 'light'
    ? 'radial-gradient(ellipse 100% 100% at 50% 50%, transparent 50%, rgba(238,234,228,0.7) 100%)'
    : 'radial-gradient(ellipse 100% 100% at 50% 50%, transparent 50%, rgba(4,3,2,0.7) 100%)';

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 0, pointerEvents: 'none' }}>
      <div style={{
        position: 'absolute', inset: 0,
        backgroundImage: `url(${imgs[idx]})`,
        backgroundSize: 'cover', backgroundPosition: 'center',
        transition: fading ? 'opacity 1.2s ease' : 'none',
        opacity: fading ? 0 : 1,
      }} />
      <div style={{
        position: 'absolute', inset: 0,
        backgroundImage: `url(${imgs[next]})`,
        backgroundSize: 'cover', backgroundPosition: 'center',
        opacity: fading ? 1 : 0,
        transition: fading ? 'opacity 1.2s ease' : 'none',
      }} />
      <div style={{ position: 'absolute', inset: 0, background: overlay }} />
      <div style={{ position: 'absolute', inset: 0, background: vignette }} />
    </div>
  );
}

// ─── Cursor-following particle canvas ──────────────────────────────────────
function ParticleCanvas() {
  const { theme } = useTheme();
  const themeRef = useRef(theme);
  useEffect(() => { themeRef.current = theme; }, [theme]);
  const ref = useRef<HTMLCanvasElement>(null);
  const mouse = useRef({ x: -9999, y: -9999 });

  useEffect(() => {
    const canvas = ref.current; if (!canvas) return;
    const ctx = canvas.getContext('2d'); if (!ctx) return;
    let raf: number;

    type P = { x: number; y: number; vx: number; vy: number; size: number; alpha: number };
    const ps: P[] = [];

    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = Math.max(document.documentElement.scrollHeight, window.innerHeight);
    };
    resize();
    window.addEventListener('resize', resize);

    const onMove = (e: MouseEvent) => { mouse.current = { x: e.clientX, y: e.clientY + window.scrollY }; };
    window.addEventListener('mousemove', onMove);

    for (let i = 0; i < 220; i++) ps.push({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      vx: (Math.random() - .5) * .3,
      vy: (Math.random() - .5) * .3,
      size: Math.random() * 1.4 + .3,
      alpha: Math.random() * .3 + .08,
    });

    function draw() {
      ctx!.clearRect(0, 0, canvas!.width, canvas!.height);
      const mx = mouse.current.x, my = mouse.current.y;

      for (const p of ps) {
        // gentle attraction to cursor within 200px
        const dx = mx - p.x, dy = my - p.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 200 && dist > 0) {
          const f = (1 - dist / 200) * 0.012;
          p.vx += dx / dist * f;
          p.vy += dy / dist * f;
        }
        // damping
        p.vx *= 0.97; p.vy *= 0.97;
        p.x += p.vx; p.y += p.vy;
        if (p.x < 0) p.x = canvas!.width; else if (p.x > canvas!.width) p.x = 0;
        if (p.y < 0) p.y = canvas!.height; else if (p.y > canvas!.height) p.y = 0;

        // boost alpha near cursor
        const nearBoost = dist < 120 ? (1 - dist / 120) * 0.4 : 0;
        ctx!.beginPath();
        ctx!.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        const [pr, pg, pb] = themeRef.current === 'light' ? [100, 75, 40] : [196, 168, 130];
        ctx!.fillStyle = `rgba(${pr},${pg},${pb},${p.alpha + nearBoost})`;
        ctx!.fill();
      }

      // draw subtle connection lines near cursor
      for (let i = 0; i < ps.length; i++) {
        for (let j = i + 1; j < ps.length; j++) {
          const dx = ps[i].x - ps[j].x, dy = ps[i].y - ps[j].y;
          const d = Math.sqrt(dx * dx + dy * dy);
          if (d < 80) {
            ctx!.beginPath();
            ctx!.strokeStyle = themeRef.current === 'light'
              ? `rgba(100,75,40,${0.06 * (1 - d / 80)})`
              : `rgba(196,168,130,${0.04 * (1 - d / 80)})`;
            ctx!.lineWidth = .4;
            ctx!.moveTo(ps[i].x, ps[i].y);
            ctx!.lineTo(ps[j].x, ps[j].y);
            ctx!.stroke();
          }
        }
      }

      raf = requestAnimationFrame(draw);
    }
    draw();

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
      window.removeEventListener('mousemove', onMove);
    };
  }, []);

  return <canvas ref={ref} style={{ position: 'fixed', inset: 0, pointerEvents: 'none', zIndex: 1, opacity: .7 }} />;
}

// ─── 3D building wireframe ──────────────────────────────────────────────────
function BuildingWireframe() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current; if (!canvas) return;
    const ctx = canvas.getContext('2d'); if (!ctx) return;
    canvas.width = 460; canvas.height = 460;
    let raf: number, rotY = 0.3;
    const W = 2.6, D = 3.4, FLOORS = 4, FH = 1.15;
    const verts: number[][] = [];
    for (let f = 0; f <= FLOORS; f++) {
      const y = f * FH;
      verts.push([-W / 2, y, -D / 2], [W / 2, y, -D / 2], [W / 2, y, D / 2], [-W / 2, y, D / 2]);
    }
    const edges: number[][] = [];
    for (let f = 0; f <= FLOORS; f++) { const b = f * 4; edges.push([b, b + 1], [b + 1, b + 2], [b + 2, b + 3], [b + 3, b]); }
    for (let c = 0; c < 4; c++) for (let f = 0; f < FLOORS; f++) edges.push([f * 4 + c, (f + 1) * 4 + c]);
    for (let f = 0; f < FLOORS; f++) {
      const y1 = (f + .5) * FH, y2 = (f + .85) * FH;
      const vBase = verts.length;
      verts.push([-W / 2, y1, -D / 2], [W / 2, y1, -D / 2], [-W / 2, y2, -D / 2], [W / 2, y2, -D / 2]);
      edges.push([vBase, vBase + 1], [vBase + 2, vBase + 3]);
      for (let m = 1; m < 3; m++) { const x = -W / 2 + m * (W / 3); const mv = verts.length; verts.push([x, y1, -D / 2], [x, y2, -D / 2]); edges.push([mv, mv + 1]); }
    }
    const totalEdges = edges.length;
    let drawn = 0, phase: 'draw' | 'rotate' = 'draw';
    const DRAW_SPEED = 2;

    function project(vx: number, vy: number, vz: number, ry: number): [number, number] {
      const cos = Math.cos(ry), sin = Math.sin(ry);
      const rx = vx * cos - vz * sin, rz = vx * sin + vz * cos;
      const FOV = 260, DIST = 7, cx = canvas!.width * .48, cy = canvas!.height * .52;
      const s = FOV / (DIST + rz);
      return [cx + rx * s, cy - vy * s + 30];
    }

    function draw() {
      ctx!.clearRect(0, 0, canvas!.width, canvas!.height);
      if (phase === 'draw') { drawn = Math.min(drawn + DRAW_SPEED, totalEdges); if (drawn >= totalEdges) phase = 'rotate'; }
      else rotY += .005;
      const edgesToDraw = phase === 'draw' ? drawn : totalEdges;
      for (let i = 0; i < edgesToDraw; i++) {
        const [a, b] = edges[i];
        if (a >= verts.length || b >= verts.length) continue;
        const [ax, ay] = project(...(verts[a] as [number, number, number]), rotY);
        const [bx, by] = project(...(verts[b] as [number, number, number]), rotY);
        const avgZ = (verts[a][2] + verts[b][2]) / 2 / (D * 1.2) + .5;
        const alpha = 0.2 + avgZ * 0.6;
        ctx!.beginPath();
        ctx!.strokeStyle = `rgba(196,168,130,${alpha})`;
        ctx!.shadowColor = 'rgba(196,168,130,0.5)';
        ctx!.shadowBlur = 4;
        ctx!.lineWidth = avgZ > .6 ? 1.1 : .65;
        ctx!.moveTo(ax, ay); ctx!.lineTo(bx, by); ctx!.stroke();
      }
      if (phase === 'rotate') {
        for (let f = 1; f <= FLOORS; f++) {
          const [px, py] = project(-W / 2 - .15, f * FH - .5, -D / 2, rotY);
          ctx!.fillStyle = 'rgba(196,168,130,0.3)';
          ctx!.font = '10px Space Grotesk,sans-serif';
          ctx!.fillText(`L${f}`, px - 18, py + 4);
        }
      }
      raf = requestAnimationFrame(draw);
    }
    draw();
    return () => cancelAnimationFrame(raf);
  }, []);
  return <canvas ref={ref} style={{ width: 460, height: 460, opacity: .85, filter: 'drop-shadow(0 0 24px rgba(196,168,130,0.2))' }} />;
}

// ─── Scroll fade-in ─────────────────────────────────────────────────────────
function FadeIn({ children, delay = 0, className = '' }: { children: React.ReactNode; delay?: number; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [vis, setVis] = useState(false);
  useEffect(() => {
    const el = ref.current; if (!el) return;
    const obs = new IntersectionObserver(([e]) => { if (e.isIntersecting) setVis(true); }, { threshold: .12 });
    obs.observe(el);
    return () => obs.disconnect();
  }, []);
  return (
    <div ref={ref} style={{
      opacity: vis ? 1 : 0,
      transform: vis ? 'translateY(0)' : 'translateY(24px)',
      transition: `opacity .8s ease ${delay}s, transform .8s ease ${delay}s`,
    }} className={className}>
      {children}
    </div>
  );
}

// ─── Splash screen ──────────────────────────────────────────────────────────
function SplashScreen({ onDone }: { onDone: () => void }) {
  const [stage, setStage] = useState(0); // 0=hidden 1=logo 2=text 3=line 4=sub 5=exit

  useEffect(() => {
    const ts = [
      setTimeout(() => setStage(1), 80),    // construction starts
      setTimeout(() => setStage(2), 80),
      setTimeout(() => setStage(3), 80),
      setTimeout(() => setStage(4), 1700),  // line extends (after bulb on ~1.5s)
      setTimeout(() => setStage(5), 1950),  // subtitle
      setTimeout(() => setStage(6), 2900),  // exit
      setTimeout(() => onDone(), 3500),
    ];
    return () => ts.forEach(clearTimeout);
  }, []);

  const leaving = stage === 6;
  const LETTERS = 'PETRONUS'.split('');

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1000,
      background: '#030201',
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      opacity: leaving ? 0 : 1,
      transition: leaving ? 'opacity .7s cubic-bezier(0.4,0,1,1)' : 'none',
      pointerEvents: leaving ? 'none' : 'all',
    }}>
      {/* Logo — full animated SVG construction */}
      <div style={{
        opacity: stage >= 1 ? 1 : 0,
        transition: 'opacity .4s ease',
        marginBottom: 20,
      }}>
        {stage >= 1 && (
          <PetronusLogo
            height={52}
            color="#c4a882"
            animated={stage >= 1}
            iconOnly={false}
          />
        )}
      </div>

      {/* Thin extending line */}
      <div style={{
        height: 1, marginBottom: 16,
        background: 'linear-gradient(90deg, transparent, rgba(196,168,130,0.45), transparent)',
        width: stage >= 4 ? 260 : 0,
        transition: 'width .7s cubic-bezier(0.22,1,0.36,1)',
      }} />

      {/* Subtitle */}
      <div style={{
        fontFamily: 'monospace', fontSize: 9, color: 'rgba(196,168,130,0.45)',
        letterSpacing: '5px', textTransform: 'uppercase',
        opacity: stage >= 5 ? 1 : 0,
        transform: stage >= 5 ? 'translateY(0)' : 'translateY(6px)',
        transition: 'opacity .6s ease, transform .6s ease',
      }}>
        Automated BIM Platform
      </div>
    </div>
  );
}

// ─── Nav drawer ─────────────────────────────────────────────────────────────
const FAKE_PROJECTS = [
  { id: '1', name: 'Fremont Infill — 4 Units', addr: '37823 Fremont Blvd, Fremont CA', date: 'Mar 12, 2026', stories: 3, units: 4, status: 'generated' },
  { id: '2', name: 'Oakland ADU Stack', addr: '2210 Telegraph Ave, Oakland CA', date: 'Mar 8, 2026', stories: 2, units: 2, status: 'generated' },
  { id: '3', name: 'San Jose Mixed-Use', addr: '115 S Market St, San Jose CA', date: 'Feb 28, 2026', stories: 3, units: 6, status: 'review' },
];

function NavDrawer({ open, onClose, router }: { open: boolean; onClose: () => void; router: any }) {
  const { theme } = useTheme(); const t = tk(theme);
  const drawerBg = theme === 'light' ? '#ede8e0' : '#0d0b09';
  return (
    <>
      {open && <div onClick={onClose} style={{ position: 'fixed', inset: 0, zIndex: 199, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(6px)' }} />}
      <div style={{
        position: 'fixed', top: 0, right: 0, bottom: 0, zIndex: 200,
        width: 340, background: drawerBg,
        borderLeft: '1px solid rgba(196,168,130,0.1)',
        transform: open ? 'translateX(0)' : 'translateX(100%)',
        transition: 'transform .4s cubic-bezier(0.22,1,0.36,1)',
        display: 'flex', flexDirection: 'column',
        boxShadow: open ? '-24px 0 80px rgba(0,0,0,0.7)' : 'none',
        overflow: 'hidden',
      }}>
        <div style={{
          padding: '20px 24px', borderBottom: '1px solid rgba(255,255,255,0.05)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <PetronusLogo height={20} color="#c4a882" iconOnly={false} />
          </div>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: t.textMute, cursor: 'pointer', fontSize: 20, lineHeight: 1, padding: 4 }}>×</button>
        </div>

        <div style={{ padding: '16px 12px 8px', borderBottom: '1px solid rgba(255,255,255,0.05)', flexShrink: 0 }}>
          <button onClick={() => { router.push('/app'); onClose(); }} style={{
            width: '100%', padding: '11px 16px', borderRadius: 10, display: 'flex', alignItems: 'center', gap: 12,
            background: 'rgba(196,168,130,0.1)', border: '1px solid rgba(196,168,130,0.25)',
            cursor: 'pointer', marginBottom: 6,
          }}>
            <Icon d={ICONS.rocket} color="#c4a882" size={15} />
            <span style={{ fontFamily: 'monospace', fontSize: 12, color: '#c4a882', fontWeight: 600 }}>Launch App</span>
            <span style={{ marginLeft: 'auto', fontFamily: 'monospace', fontSize: 10, color: '#c4a882', opacity: .5 }}>→</span>
          </button>
          {([
            { iconKey: 'layers' as const,  label: 'Dashboard',   sub: 'Overview & analytics',   href: '/dashboard', live: true  },
            { iconKey: 'blueprint' as const, label: 'My Projects', sub: 'Saved building models',  href: '/projects',  live: false },
            { iconKey: 'gear' as const,    label: 'Settings',    sub: 'Account & preferences',   href: '/settings',  live: true  },
          ]).map(item => (
            item.live ? (
              <button key={item.label} onClick={() => { router.push(item.href); onClose(); }} style={{
                width: '100%', padding: '11px 16px', borderRadius: 10, display: 'flex', alignItems: 'center', gap: 12,
                background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)',
                cursor: 'pointer', marginBottom: 6, transition: 'all .15s',
              }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(196,168,130,0.06)'; (e.currentTarget as HTMLElement).style.borderColor = 'rgba(196,168,130,0.18)'; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.02)'; (e.currentTarget as HTMLElement).style.borderColor = 'rgba(255,255,255,0.05)'; }}
              >
                <Icon d={ICONS[item.iconKey]} color="#5a5550" size={14} />
                <div style={{ textAlign: 'left' }}>
                  <div style={{ fontFamily: 'monospace', fontSize: 12, color: t.textSub }}>{item.label}</div>
                  <div style={{ fontFamily: 'monospace', fontSize: 9, color: t.textDim, marginTop: 1 }}>{item.sub}</div>
                </div>
                <span style={{ marginLeft: 'auto', fontFamily: 'monospace', fontSize: 10, color: t.textDim, opacity: .5 }}>→</span>
              </button>
            ) : (
              <div key={item.label} style={{
                width: '100%', padding: '11px 16px', borderRadius: 10, display: 'flex', alignItems: 'center', gap: 12,
                background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)',
                cursor: 'default', marginBottom: 6, opacity: .4,
              }}>
                <Icon d={ICONS[item.iconKey]} color="#5a5550" size={14} />
                <div>
                  <div style={{ fontFamily: 'monospace', fontSize: 12, color: t.textSub }}>{item.label}</div>
                  <div style={{ fontFamily: 'monospace', fontSize: 9, color: t.textDim, marginTop: 1 }}>{item.sub}</div>
                </div>
                <span style={{ marginLeft: 'auto', fontFamily: 'monospace', fontSize: 8, color: '#c4a882', background: 'rgba(196,168,130,0.08)', border: '1px solid rgba(196,168,130,0.18)', borderRadius: 4, padding: '2px 6px', letterSpacing: '1px' }}>SOON</span>
              </div>
            )
          ))}
        </div>

        <div style={{ flex: 1, overflow: 'auto', padding: '16px 12px' }}>
          <div style={{ fontFamily: 'monospace', fontSize: 9, color: 'rgba(196,168,130,0.4)', letterSpacing: '3px', textTransform: 'uppercase', marginBottom: 12, paddingLeft: 4 }}>
            Recent Projects
          </div>
          {FAKE_PROJECTS.map(p => (
            <div key={p.id} style={{
              padding: '14px 16px', borderRadius: 10, marginBottom: 8, position: 'relative',
              background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)',
            }}>
              <div style={{
                position: 'absolute', inset: 0, borderRadius: 10, zIndex: 2,
                background: 'rgba(8,6,5,0.7)', backdropFilter: 'blur(2px)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                <span style={{ fontFamily: 'monospace', fontSize: 9, color: '#c4a882', background: 'rgba(196,168,130,0.08)', border: '1px solid rgba(196,168,130,0.18)', borderRadius: 6, padding: '4px 10px', letterSpacing: '2px' }}>UNDER CONSTRUCTION</span>
              </div>
              <div style={{ fontFamily: 'Space Grotesk,sans-serif', fontWeight: 600, fontSize: 13, color: t.textSub, marginBottom: 4 }}>{p.name}</div>
              <div style={{ fontFamily: 'monospace', fontSize: 10, color: t.textDim, marginBottom: 6 }}>{p.addr}</div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                <Tag color='#c4a882'>{p.stories} stories</Tag>
                <Tag color='#8fa898'>{p.units} units</Tag>
                <Tag color={p.status === 'review' ? '#d4943a' : '#7a7a8a'}>{p.status}</Tag>
                <Tag color='#4a4540'>{p.date}</Tag>
              </div>
            </div>
          ))}
        </div>

        <div style={{ padding: '14px 24px', borderTop: '1px solid rgba(255,255,255,0.05)', flexShrink: 0 }}>
          <div style={{ fontFamily: 'monospace', fontSize: 9, color: '#2a2520', letterSpacing: '2px', textAlign: 'center' }}>
            v0.1.0 · BETA · California Multi-family
          </div>
        </div>
      </div>
    </>
  );
}

function Tag({ children, color }: { children: React.ReactNode; color: string }) {
  return (
    <span style={{ fontFamily: 'monospace', fontSize: 9, color, background: `${color}18`, border: `1px solid ${color}28`, borderRadius: 4, padding: '2px 6px' }}>
      {children}
    </span>
  );
}

// ─── Main page ──────────────────────────────────────────────────────────────
export default function LandingPage() {
  const router = useRouter();
  const [showContent, setShowContent] = useState(false);
  const [splashDone, setSplashDone] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [theme, setTheme] = useState<Theme>('dark');
  const overlayRef = useRef<HTMLDivElement>(null);

  // Load persisted theme
  useEffect(() => {
    const saved = localStorage.getItem('petronus_theme') as Theme | null;
    const initial: Theme = saved === 'light' ? 'light' : 'dark';
    setTheme(initial);
    document.documentElement.setAttribute('data-theme', initial);
  }, []);

  const toggleTheme = useCallback(() => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark';
    const nextBg = next === 'light' ? '#f8f6f3' : '#060504';
    const el = overlayRef.current;
    if (!el) return;

    // Reset to invisible at destination color, then fade in
    el.style.background = nextBg;
    el.style.transition = 'none';
    el.style.opacity = '0';
    requestAnimationFrame(() => requestAnimationFrame(() => {
      el.style.transition = 'opacity 0.18s ease-in';
      el.style.opacity = '1';
    }));

    // Swap theme while fully covered, then fade out slowly
    setTimeout(() => {
      setTheme(next);
      localStorage.setItem('petronus_theme', next);
      document.documentElement.setAttribute('data-theme', next);
      el.style.transition = 'opacity 0.52s cubic-bezier(0.4,0,0.2,1)';
      el.style.opacity = '0';
    }, 220);
  }, [theme]);

  useEffect(() => {
    document.documentElement.classList.remove('app-page');
    document.body.classList.remove('app-page');
    const isReload = (performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming)?.type === 'reload';
    const alreadySeen = sessionStorage.getItem('petronus_splash') === '1';
    if (alreadySeen && !isReload) { setSplashDone(true); setShowContent(true); }
  }, []);

  useEffect(() => { if (splashDone) setShowContent(true); }, [splashDone]);

  const t = tk(theme);
  const bg = theme === 'light' ? '#f8f6f3' : '#060504';
  const textColor = t.text;
  const accentColor = t.accent;
  const mutedColor = t.textSub;
  const navBg = theme === 'light' ? 'rgba(248,246,243,0.82)' : 'rgba(6,5,4,0.7)';
  const borderColor = t.border;

  return (
    <ThemeCtx.Provider value={{ theme, toggle: toggleTheme }}>
    <div style={{ background: bg, minHeight: '100vh', position: 'relative', overflowX: 'clip' }}>
      <ArchBackground />
      {!splashDone && <SplashScreen onDone={() => { sessionStorage.setItem('petronus_splash', '1'); setSplashDone(true); }} />}
      <NavDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} router={router} />
      <ParticleCanvas />

      {/* ── Nav ── */}
      <nav style={{
        position: 'sticky', top: 0, zIndex: 100,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '14px 40px',
        background: navBg,
        backdropFilter: 'blur(20px)',
        borderBottom: `1px solid ${borderColor}`,
      }}>
        <PetronusLogo height={22} color="#c4a882" iconOnly={false} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <SpotlightBtn onClick={() => router.push('/billing')}
            accent="#c4a882" border="transparent" textColor={t.textMute}
            style={{ borderRadius: 8, padding: '7px 12px', fontFamily: 'monospace', fontSize: 12, background: 'transparent' }}>
            Pricing
          </SpotlightBtn>
          <SpotlightBtn onClick={() => router.push('/login')}
            accent="#c4a882" border={borderColor} textColor={mutedColor}
            style={{ borderRadius: 8, padding: '7px 16px', fontFamily: 'monospace', fontSize: 12 }}>
            Sign in
          </SpotlightBtn>
          <SpotlightBtn onClick={toggleTheme}
            accent={t.accent} border={borderColor} textColor={t.textMute}
            style={{ borderRadius: 8, padding: '8px 10px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <Icon d={theme === 'dark' ? ICONS.sun : ICONS.moon} size={15} color={t.textMute} />
          </SpotlightBtn>
          <button onClick={() => setDrawerOpen(o => !o)} style={{
            background: drawerOpen ? 'rgba(196,168,130,0.08)' : 'rgba(255,255,255,0.03)',
            border: `1px solid ${drawerOpen ? 'rgba(196,168,130,0.25)' : 'rgba(255,255,255,0.07)'}`,
            borderRadius: 8, padding: '9px 11px', cursor: 'pointer',
            display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 4,
            transition: 'all .2s',
          }}>
            <div style={{ width: 20, height: 1.5, background: drawerOpen ? '#c4a882' : '#8a8278', borderRadius: 1, transition: 'transform .3s cubic-bezier(0.22,1,0.36,1), background .2s', transformOrigin: 'right center', transform: drawerOpen ? 'translateY(5.5px) rotate(40deg) scaleX(0.82)' : 'none' }} />
            <div style={{ width: 20, height: 1.5, background: '#8a8278', borderRadius: 1, transition: 'opacity .2s, transform .3s', opacity: drawerOpen ? 0 : 1, transform: drawerOpen ? 'scaleX(0)' : 'none' }} />
            <div style={{ width: 20, height: 1.5, background: drawerOpen ? '#c4a882' : '#8a8278', borderRadius: 1, transition: 'transform .3s cubic-bezier(0.22,1,0.36,1), background .2s', transformOrigin: 'right center', transform: drawerOpen ? 'translateY(-5.5px) rotate(-40deg) scaleX(0.82)' : 'none' }} />
          </button>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section style={{
        position: 'relative', zIndex: 2,
        minHeight: '100vh', display: 'flex', alignItems: 'center',
        padding: '0 40px', overflow: 'hidden',
      }}>
        <div style={{
          position: 'absolute', inset: 0, pointerEvents: 'none',
          background: 'radial-gradient(ellipse 60% 70% at 28% 55%, rgba(196,168,130,0.04) 0%, transparent 60%)',
        }} />

        <div style={{ flex: '0 0 50%', paddingLeft: '4vw', zIndex: 2 }}>
          <div style={{
            opacity: showContent ? 1 : 0,
            transform: showContent ? 'translateY(0)' : 'translateY(24px)',
            transition: 'opacity .9s ease, transform .9s ease',
          }}>
            <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#c4a882', letterSpacing: '4px', textTransform: 'uppercase', marginBottom: 20, opacity: .6 }}>
              Automated BIM Platform
            </div>
            <h1 style={{
              margin: '0 0 22px', lineHeight: 1.02,
              fontFamily: 'Space Grotesk,sans-serif', fontWeight: 700, fontSize: 'clamp(46px,5.5vw,76px)',
              color: textColor,
            }}>
              Design buildings.<br />
              <span style={{ color: accentColor }}>Not spreadsheets.</span>
            </h1>
            <p style={{ fontFamily: 'DM Sans,sans-serif', fontSize: 17, color: t.textMute, lineHeight: 1.75, maxWidth: 480, margin: '0 0 38px' }}>
              Drop a pin on any California parcel. Petronus generates an architectural + MEP concept model in under 30 seconds — including site analysis, floor plans, routed systems, and a multi-code preliminary preflight.
            </p>
            <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap' }}>
              <EnterButton onClick={() => router.push('/app')} />
              <SpotlightBtn onClick={() => document.getElementById('how')?.scrollIntoView({ behavior: 'smooth' })}
                accent="rgba(255,255,255,0.6)" border="rgba(255,255,255,0.15)" textColor={t.textMute}
                style={{ padding: '13px 26px', borderRadius: 10, fontFamily: 'monospace', fontSize: 12 }}>
                See how it works
              </SpotlightBtn>
            </div>
            <div style={{ display: 'flex', gap: 36, marginTop: 52 }}>
              {[['< 30s', 'Generation time'], ['Multi-code', 'Preflight scope'], ['3', 'Massing options'], ['Routed', 'MEP systems']].map(([val, lbl]) => (
                <div key={lbl}>
                  <div style={{ fontFamily: 'Space Grotesk,sans-serif', fontWeight: 700, fontSize: 22, color: '#c4a882' }}>{val}</div>
                  <div style={{ fontFamily: 'monospace', fontSize: 9, color: t.textDim, marginTop: 3, letterSpacing: '1px', textTransform: 'uppercase' }}>{lbl}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div style={{ flex: '0 0 50%', display: 'flex', alignItems: 'center', justifyContent: 'center', opacity: showContent ? 1 : 0, transition: 'opacity 1.4s ease .4s' }}>
          <BuildingWireframe />
        </div>
      </section>

      {/* ── Features ── */}
      <section style={{ position: 'relative', zIndex: 2, padding: '100px 40px', maxWidth: 1200, margin: '0 auto' }}>
        <FadeIn>
          <div style={{ textAlign: 'center', marginBottom: 64 }}>
            <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#c4a882', letterSpacing: '4px', textTransform: 'uppercase', marginBottom: 12, opacity: .6 }}>Capabilities</div>
            <h2 style={{ fontFamily: 'Space Grotesk,sans-serif', fontWeight: 700, fontSize: 'clamp(26px,3.5vw,42px)', margin: 0, color: textColor }}>Everything in one pipeline</h2>
          </div>
        </FadeIn>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(260px,1fr))', gap: 18 }}>
          {FEATURES.map((f, i) => (
            <FadeIn key={f.title} delay={i * .07}>
              <FeatureCard iconKey={f.iconKey} title={f.title} desc={f.desc} color={f.color} />
            </FadeIn>
          ))}
        </div>
      </section>

      {/* ── How it works ── */}
      <section id="how" style={{ position: 'relative', zIndex: 2, padding: '100px 40px', background: 'linear-gradient(180deg,transparent,rgba(196,168,130,0.015) 40%,transparent)' }}>
        <div style={{ maxWidth: 900, margin: '0 auto' }}>
          <FadeIn>
            <div style={{ textAlign: 'center', marginBottom: 72 }}>
              <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#8fa898', letterSpacing: '4px', textTransform: 'uppercase', marginBottom: 12, opacity: .7 }}>Workflow</div>
              <h2 style={{ fontFamily: 'Space Grotesk,sans-serif', fontWeight: 700, fontSize: 'clamp(26px,3.5vw,42px)', margin: 0, color: textColor }}>From parcel to BIM in 4 steps</h2>
            </div>
          </FadeIn>
          <div style={{ position: 'relative' }}>
            <div style={{ position: 'absolute', left: 'calc(50% - .5px)', top: 32, bottom: 32, width: 1, background: 'linear-gradient(180deg,rgba(196,168,130,0.2),rgba(143,168,152,0.2))', zIndex: 0 }} />
            {STEPS.map((s, i) => (
              <FadeIn key={s.title} delay={i * .1}>
                <StepCard step={s} index={i} />
              </FadeIn>
            ))}
          </div>
        </div>
      </section>

      {/* ── Terminal section ── */}
      <section style={{ position: 'relative', zIndex: 2, padding: '100px 40px', background: 'linear-gradient(180deg,transparent,rgba(20,15,10,0.4) 50%,transparent)' }}>
        <div style={{ maxWidth: 1100, margin: '0 auto', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 64, alignItems: 'center' }}>
          <FadeIn>
            <div>
              <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#8fa898', letterSpacing: '4px', textTransform: 'uppercase', marginBottom: 16, opacity: .7 }}>Live Pipeline</div>
              <h2 style={{ fontFamily: 'Space Grotesk,sans-serif', fontWeight: 700, fontSize: 'clamp(24px,3vw,38px)', margin: '0 0 20px', color: textColor }}>Watch the model build itself</h2>
              <p style={{ fontFamily: 'DM Sans,sans-serif', fontSize: 15, color: t.textMute, lineHeight: 1.8, margin: '0 0 32px' }}>Every stage streams in real time — site data, massing, rooms, MEP routing, and preliminary preflight. You see exactly what's happening and why.</p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {[
                  { step: '01', label: 'Site context', detail: 'OSM + FEMA + USGS in parallel', color: '#c4a882' },
                  { step: '02', label: 'Massing', detail: '3 options, scored by priority', color: '#8fa898' },
                  { step: '03', label: 'Floorplan', detail: 'Units clipped to actual footprint', color: '#c4a882' },
                  { step: '04', label: 'MEP routing', detail: 'Plumbing, electrical, HVAC', color: '#d4943a' },
                  { step: '05', label: 'Preflight', detail: 'California multi-code preliminary review', color: '#8fa898' },
                ].map(item => (
                  <div key={item.step} style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
                    <div style={{ fontFamily: 'monospace', fontSize: 10, color: item.color, opacity: .55, flexShrink: 0, width: 24 }}>{item.step}</div>
                    <div style={{ flex: 1, height: 1, background: `linear-gradient(90deg,${item.color}35,transparent)` }} />
                    <div style={{ fontFamily: 'monospace', fontSize: 12, color: t.textSub, flexShrink: 0 }}>{item.label}</div>
                    <div style={{ fontFamily: 'monospace', fontSize: 10, color: t.textDim, flexShrink: 0, maxWidth: 180, textAlign: 'right' }}>{item.detail}</div>
                  </div>
                ))}
              </div>
            </div>
          </FadeIn>
          <FadeIn delay={.15}><TerminalBlock /></FadeIn>
        </div>
      </section>

      {/* ── Stats bar ── */}
      <section style={{ position: 'relative', zIndex: 2, padding: '60px 40px' }}>
        <FadeIn>
          <div style={{
            maxWidth: 1000, margin: '0 auto', display: 'grid',
            gridTemplateColumns: 'repeat(4,1fr)', gap: 1,
            border: '1px solid rgba(255,255,255,0.04)', borderRadius: 20, overflow: 'hidden',
          }}>
            {[
              { val: '< 30s', label: 'Full generation', sub: 'from pin to 3D model', color: '#c4a882' },
              { val: 'Multi-code', label: 'Preflight', sub: 'CBC · CRC · CEC · Title 24', color: '#8fa898' },
              { val: '3', label: 'Massing options', sub: 'rectangle · L-shape · bar', color: '#c4a882' },
              { val: '100%', label: 'CA-specific', sub: 'built for California parcels', color: '#d4943a' },
            ].map((s, i) => (
              <div key={s.label} style={{
                padding: '36px 24px', textAlign: 'center',
                background: i % 2 === 0 ? 'rgba(255,255,255,0.015)' : 'rgba(255,255,255,0.008)',
                borderRight: i < 3 ? '1px solid rgba(255,255,255,0.04)' : 'none',
              }}>
                <div style={{ fontFamily: 'Space Grotesk,sans-serif', fontWeight: 700, fontSize: 34, color: s.color, marginBottom: 8 }}>{s.val}</div>
                <div style={{ fontFamily: 'Space Grotesk,sans-serif', fontWeight: 600, fontSize: 13, color: t.textSub, marginBottom: 4 }}>{s.label}</div>
                <div style={{ fontFamily: 'monospace', fontSize: 9, color: t.textDim, letterSpacing: '.5px' }}>{s.sub}</div>
              </div>
            ))}
          </div>
        </FadeIn>
      </section>

      {/* ── Why section ── */}
      <section style={{ position: 'relative', zIndex: 2, padding: '100px 40px', background: 'linear-gradient(180deg,transparent,rgba(196,168,130,0.012) 50%,transparent)' }}>
        <div style={{ maxWidth: 1100, margin: '0 auto' }}>
          <FadeIn>
            <div style={{ textAlign: 'center', marginBottom: 64 }}>
              <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#8fa898', letterSpacing: '4px', textTransform: 'uppercase', marginBottom: 12, opacity: .7 }}>Why Petronus</div>
              <h2 style={{ fontFamily: 'Space Grotesk,sans-serif', fontWeight: 700, fontSize: 'clamp(26px,3.5vw,42px)', margin: 0, color: textColor }}>Replace the manual process</h2>
            </div>
          </FadeIn>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
            <FadeIn delay={0}>
              <div style={{ padding: 32, borderRadius: 18, border: '1px solid rgba(180,60,60,0.18)', background: 'rgba(180,60,60,0.025)' }}>
                <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#b04040', letterSpacing: '3px', textTransform: 'uppercase', marginBottom: 24, opacity: .8 }}>Traditional workflow</div>
                {['Days of manual site research', 'Schematic massing in Revit or SketchUp', 'Separate MEP consultant coordination', 'Code consultant for compliance review', 'Multiple revision cycles per schema', 'No real-time neighbor data'].map(item => (
                  <div key={item} style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
                    <div style={{ width: 16, height: 16, borderRadius: '50%', border: '1px solid rgba(176,64,64,0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                      <div style={{ width: 6, height: 1.5, background: '#b04040', borderRadius: 1 }} />
                    </div>
                    <span style={{ fontFamily: 'DM Sans,sans-serif', fontSize: 14, color: t.textDim }}>{item}</span>
                  </div>
                ))}
              </div>
            </FadeIn>
            <FadeIn delay={.1}>
              <div style={{ padding: 32, borderRadius: 18, border: '1px solid rgba(196,168,130,0.2)', background: 'rgba(196,168,130,0.025)' }}>
                <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#c4a882', letterSpacing: '3px', textTransform: 'uppercase', marginBottom: 24, opacity: .8 }}>With Petronus</div>
                {['Site data fetched instantly from OSM + FEMA', '3 massing options generated in seconds', 'MEP routing runs inside the same pipeline', 'Multi-code preliminary preflight at generation time', 'One click → coordinated concept model', 'Real OSM neighbor buildings in 3D'].map(item => (
                  <div key={item} style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
                    <div style={{ width: 16, height: 16, borderRadius: '50%', border: '1px solid rgba(196,168,130,0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                      <div style={{ width: 5, height: 5, background: '#c4a882', borderRadius: '50%' }} />
                    </div>
                    <span style={{ fontFamily: 'DM Sans,sans-serif', fontSize: 14, color: t.textSub }}>{item}</span>
                  </div>
                ))}
              </div>
            </FadeIn>
          </div>
        </div>
      </section>

      {/* ── Tech stack ── */}
      <section style={{ position: 'relative', zIndex: 2, padding: '80px 40px' }}>
        <div style={{ maxWidth: 1100, margin: '0 auto' }}>
          <FadeIn>
            <div style={{ textAlign: 'center', marginBottom: 52 }}>
              <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#c4a882', letterSpacing: '4px', textTransform: 'uppercase', marginBottom: 12, opacity: .6 }}>Built With</div>
              <h2 style={{ fontFamily: 'Space Grotesk,sans-serif', fontWeight: 700, fontSize: 'clamp(22px,2.8vw,34px)', margin: 0, color: textColor }}>A real engineering stack</h2>
            </div>
          </FadeIn>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(200px,1fr))', gap: 14 }}>
            {([
              { name: 'FastAPI',       role: 'Backend pipeline',     color: '#c4a882', iconKey: 'bolt'     },
              { name: 'Next.js 14',    role: 'App Router + SSR',     color: '#f0ece4', iconKey: 'triangle' },
              { name: 'Three.js',      role: '3D model viewer',      color: '#8fa898', iconKey: 'cube'     },
              { name: 'MapLibre GL',   role: 'Vector map tiles',     color: '#c4a882', iconKey: 'map_pin'  },
              { name: 'Shapely',       role: 'Parcel geometry',      color: '#d4943a', iconKey: 'layers'   },
              { name: 'OpenStreetMap', role: 'Neighbor buildings',   color: '#8fa898', iconKey: 'globe'    },
              { name: 'USGS + FEMA',   role: 'Seismic + flood data', color: '#c4a882', iconKey: 'mountain' },
              { name: 'wttr.in',       role: 'Real-time weather',    color: t.textSub, iconKey: 'weather'  },
            ] as { name: string; role: string; color: string; iconKey: keyof typeof ICONS }[]).map((tech, i) => (
              <FadeIn key={tech.name} delay={i * .05}>
                <div style={{ padding: '18px 20px', borderRadius: 12, border: `1px solid ${t.border}`, background: t.card, transition: 'all .2s' }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = t.cardHover; (e.currentTarget as HTMLElement).style.borderColor = t.borderAccent; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = t.card; (e.currentTarget as HTMLElement).style.borderColor = t.border; }}
                >
                  <div style={{ marginBottom: 10, opacity: .65 }}>
                    <Icon d={ICONS[tech.iconKey]} color={tech.color} size={18} />
                  </div>
                  <div style={{ fontFamily: 'Space Grotesk,sans-serif', fontWeight: 600, fontSize: 14, color: tech.color, marginBottom: 3 }}>{tech.name}</div>
                  <div style={{ fontFamily: 'monospace', fontSize: 9, color: t.textDim, letterSpacing: '.5px' }}>{tech.role}</div>
                </div>
              </FadeIn>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA ── */}
      <section style={{ position: 'relative', zIndex: 2, padding: '80px 40px' }}>
        <FadeIn>
          <div style={{
            maxWidth: 760, margin: '0 auto', padding: '64px 48px', borderRadius: 22, textAlign: 'center',
            background: 'rgba(196,168,130,0.04)',
            border: '1px solid rgba(196,168,130,0.14)',
            boxShadow: '0 0 80px rgba(196,168,130,0.04)',
          }}>
            <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#c4a882', letterSpacing: '4px', textTransform: 'uppercase', marginBottom: 16, opacity: .6 }}>Ready to build</div>
            <h2 style={{ fontFamily: 'Space Grotesk,sans-serif', fontWeight: 700, fontSize: 'clamp(26px,3.5vw,44px)', margin: '0 0 20px', color: textColor }}>Drop your first pin</h2>
            <p style={{ fontFamily: 'DM Sans,sans-serif', fontSize: 15, color: t.textMute, lineHeight: 1.75, margin: '0 0 36px', maxWidth: 440, marginLeft: 'auto', marginRight: 'auto' }}>
              No login. No setup. Click any California parcel and get a full building model in under 30 seconds.
            </p>
            <EnterButton onClick={() => router.push('/app')} />
          </div>
        </FadeIn>
      </section>

      <div style={{ height: 1, margin: '0 40px', background: 'linear-gradient(90deg,transparent,rgba(196,168,130,0.3),transparent)' }} />

      {/* ── Footer ── */}
      <footer style={{ position: 'relative', zIndex: 2, padding: '80px 40px 48px', background: 'linear-gradient(180deg,transparent,rgba(4,3,2,0.5))' }}>
        <div style={{ maxWidth: 1100, margin: '0 auto' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: 48, marginBottom: 60 }}>
            <FadeIn>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 }}>
                  <PetronusLogo height={24} color="#c4a882" iconOnly={false} />
                </div>
                <p style={{ fontFamily: 'DM Sans,sans-serif', fontSize: 14, color: t.textMute, lineHeight: 1.8, maxWidth: 360, margin: '0 0 16px' }}>
                  Automated BIM platform built for California residential development. We accelerate early design with concept building models, coordinated MEP routing, and clearly labeled preliminary preflight findings.
                </p>
              </div>
            </FadeIn>
            <FadeIn delay={.1}>
              <div>
                <div style={{ fontFamily: 'monospace', fontSize: 9, color: '#c4a882', letterSpacing: '3px', textTransform: 'uppercase', marginBottom: 20, opacity: .6 }}>Platform</div>
                {['Site Analysis', 'Massing Generator', 'Floorplan Layout', 'MEP Routing', 'Code Preflight', 'Facade Design'].map(l => (
                  <div key={l} style={{ fontFamily: 'DM Sans,sans-serif', fontSize: 13, color: t.textDim, marginBottom: 10 }}>{l}</div>
                ))}
              </div>
            </FadeIn>
            <FadeIn delay={.15}>
              <div>
                <div style={{ fontFamily: 'monospace', fontSize: 9, color: '#8fa898', letterSpacing: '3px', textTransform: 'uppercase', marginBottom: 20, opacity: .6 }}>Built For</div>
                {['California Residential', 'Multi-family Projects', 'CBC Preflight', 'R-2 Occupancy', 'Title 24', 'ASCE 7-22'].map(l => (
                  <div key={l} style={{ fontFamily: 'DM Sans,sans-serif', fontSize: 13, color: t.textDim, marginBottom: 10 }}>{l}</div>
                ))}
              </div>
            </FadeIn>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16, paddingTop: 24, borderTop: '1px solid rgba(255,255,255,0.04)' }}>
            <span style={{ fontFamily: 'monospace', fontSize: 10, color: '#2a2520' }}>© 2026 Petronus · All rights reserved</span>
            <span style={{ fontFamily: 'monospace', fontSize: 9, color: '#2a2520', letterSpacing: '2px' }}>v0.1.0 · BETA · California Multi-family Residential</span>
          </div>
        </div>
      </footer>
    </div>

    {/* Theme transition overlay — fades in over page, theme swaps underneath, fades out */}
    <div ref={overlayRef} style={{
      position: 'fixed', inset: 0, zIndex: 997,
      opacity: 0, pointerEvents: 'none',
    }} />
    </ThemeCtx.Provider>
  );
}

// ─── Terminal block ──────────────────────────────────────────────────────────
function TerminalBlock() {
  const { theme } = useTheme(); const t = tk(theme);
  // Terminal always has dark background — use fixed light-on-dark colors
  const lines = [
    { text: '$ petronus generate --site "Fremont, CA"', color: '#c4a882', delay: 0 },
    { text: '  ↳ Fetching site context…',               color: '#6a6460', delay: 400 },
    { text: '  ✓ Parcel: 5,840 sqft  Flood: X  Seismic: D', color: '#7db896', delay: 900 },
    { text: '  ✓ Terrain: slope 2.1% (1.2°) — flat',   color: '#7db896', delay: 1300 },
    { text: '  ↳ Generating 3 massing options…',        color: '#6a6460', delay: 1700 },
    { text: '  ✓ Option A: Rectangle  Score: 87',       color: '#7db896', delay: 2200 },
    { text: '  ✓ Option B: L-Shape    Score: 74',       color: '#7db896', delay: 2500 },
    { text: '  ✓ Option C: Bar        Score: 81',       color: '#7db896', delay: 2800 },
    { text: '  ↳ Generating floorplan (14 rooms)…',     color: '#6a6460', delay: 3200 },
    { text: '  ✓ 6 units · corridor · stair core',     color: '#7db896', delay: 3700 },
    { text: '  ↳ Routing MEP systems…',                 color: '#6a6460', delay: 4100 },
    { text: '  ✓ 12 plumbing · 18 electrical · 9 HVAC', color: '#7db896', delay: 4600 },
    { text: '  ↳ Running preliminary preflight…',        color: '#6a6460', delay: 5000 },
    { text: '  ✓ Preliminary checks · 2 review items · CA 2025', color: '#7db896', delay: 5500 },
    { text: '  ✓ Concept model ready  [27.4s]',         color: '#c4a882', delay: 6000 },
  ];
  const [visCount, setVisCount] = useState(0);
  useEffect(() => {
    const timers = lines.map((l, i) => setTimeout(() => setVisCount(n => Math.max(n, i + 1)), l.delay + 800));
    return () => timers.forEach(clearTimeout);
  }, []);
  return (
    <div style={{
      background: '#0a0806', border: `1px solid ${t.borderAccent}`, borderRadius: 14,
      padding: '22px 26px', fontFamily: 'JetBrains Mono,monospace', fontSize: 12, lineHeight: 1.8,
      boxShadow: '0 0 40px rgba(0,0,0,0.25)',
    }}>
      <div style={{ display: 'flex', gap: 7, marginBottom: 16 }}>
        {['#ff5f57', '#ffbd2e', '#28c840'].map(c => (
          <div key={c} style={{ width: 11, height: 11, borderRadius: '50%', background: c }} />
        ))}
        <span style={{ fontFamily: 'JetBrains Mono,monospace', fontSize: 11, color: '#5a5450', marginLeft: 8 }}>petronus — terminal</span>
      </div>
      {lines.slice(0, visCount).map((l, i) => (
        <div key={i} style={{ color: l.color, opacity: i === visCount - 1 ? 1 : 0.85 }}>
          {l.text}
          {i === visCount - 1 && visCount < lines.length && (
            <span style={{ borderRight: '1.5px solid #c4a882', marginLeft: 2, animation: 'blink 1s step-end infinite' }}>&nbsp;</span>
          )}
        </div>
      ))}
      {visCount === 0 && <div style={{ color: '#2a2520' }}>_</div>}
    </div>
  );
}

// ─── Spotlight button — cursor-tracking radial gradient ──────────────────────
function SpotlightBtn({
  onClick, children, accent = '#c4a882', border, baseColor, textColor: tc, style = {},
}: {
  onClick?: () => void;
  children: React.ReactNode;
  accent?: string;
  border?: string;
  baseColor?: string;
  textColor?: string;
  style?: React.CSSProperties;
}) {
  const ref = useRef<HTMLButtonElement>(null);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const [on, setOn] = useState(false);

  const move = (e: React.MouseEvent) => {
    const r = ref.current?.getBoundingClientRect();
    if (r) setPos({ x: e.clientX - r.left, y: e.clientY - r.top });
  };

  return (
    <button ref={ref} onClick={onClick}
      onMouseMove={move} onMouseEnter={() => setOn(true)} onMouseLeave={() => setOn(false)}
      style={{
        position: 'relative', overflow: 'hidden',
        cursor: 'pointer', transition: 'border-color .2s, transform .2s, box-shadow .2s',
        transform: on ? 'translateY(-1px)' : 'none',
        background: baseColor ?? 'rgba(255,255,255,0.02)',
        border: `1px solid ${on ? (border ?? accent) : (border ? `${border}55` : 'rgba(196,168,130,0.18)')}`,
        boxShadow: on ? `0 4px 28px ${accent}18` : 'none',
        color: tc ?? accent,
        ...style,
      }}>
      {/* Spotlight overlay — follows the cursor */}
      <span style={{
        position: 'absolute', inset: 0, pointerEvents: 'none', borderRadius: 'inherit',
        background: on
          ? `radial-gradient(circle 80px at ${pos.x}px ${pos.y}px, ${accent}28 0%, transparent 70%)`
          : 'transparent',
        transition: 'background .05s',
      }} />
      <span style={{ position: 'relative', zIndex: 1 }}>{children}</span>
    </button>
  );
}

// ─── Enter button ────────────────────────────────────────────────────────────
function EnterButton({ onClick }: { onClick: () => void }) {
  const { theme } = useTheme(); const t = tk(theme);
  return (
    <SpotlightBtn onClick={onClick} accent="#c4a882" textColor={t.accent}
      style={{ padding: '13px 30px', borderRadius: 10, fontFamily: 'monospace', fontSize: 12, fontWeight: 600, letterSpacing: '.5px' }}>
      Launch Petronus →
    </SpotlightBtn>
  );
}

// ─── Feature card ────────────────────────────────────────────────────────────
function FeatureCard({ iconKey, title, desc, color }: { iconKey: keyof typeof ICONS; title: string; desc: string; color: string }) {
  const { theme } = useTheme(); const t = tk(theme);
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ x: 0, y: 0 });
  const [on, setOn] = useState(false);
  const move = (e: React.MouseEvent) => {
    const r = ref.current?.getBoundingClientRect();
    if (r) setPos({ x: e.clientX - r.left, y: e.clientY - r.top });
  };
  return (
    <div ref={ref} onMouseMove={move} onMouseEnter={() => setOn(true)} onMouseLeave={() => setOn(false)}
      style={{
        padding: 26, borderRadius: 14, transition: 'all .28s ease', cursor: 'default',
        position: 'relative', overflow: 'hidden',
        background: t.card,
        border: `1px solid ${on ? t.borderAccent : t.border}`,
        boxShadow: on ? `0 0 28px ${color}10` : 'none',
        transform: on ? 'translateY(-3px)' : 'none',
      }}>
      <span style={{
        position: 'absolute', inset: 0, pointerEvents: 'none', borderRadius: 'inherit',
        background: on ? `radial-gradient(circle 100px at ${pos.x}px ${pos.y}px, ${color}18 0%, transparent 70%)` : 'transparent',
        transition: 'background .05s',
      }} />
      <div style={{ position: 'relative', zIndex: 1 }}>
        <div style={{ marginBottom: 16, opacity: on ? 1 : 0.7, transition: 'opacity .28s' }}>
          <Icon d={ICONS[iconKey]} color={color} size={22} />
        </div>
        <h3 style={{ fontFamily: 'Space Grotesk,sans-serif', fontWeight: 600, fontSize: 16, color: t.text, margin: '0 0 10px' }}>{title}</h3>
        <p style={{ fontFamily: 'DM Sans,sans-serif', fontSize: 13, color: t.textMute, lineHeight: 1.75, margin: 0 }}>{desc}</p>
      </div>
    </div>
  );
}

// ─── Step card ───────────────────────────────────────────────────────────────
function StepCard({ step, index }: { step: typeof STEPS[0]; index: number }) {
  const { theme } = useTheme(); const t = tk(theme);
  const isLeft = index % 2 === 0;
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 24, marginBottom: 48, flexDirection: isLeft ? 'row' : 'row-reverse' }}>
      <div style={{ flex: '0 0 calc(50% - 32px)', textAlign: isLeft ? 'right' : 'left' }}>
        <div style={{ fontFamily: 'monospace', fontSize: 9, color: step.color, letterSpacing: '3px', textTransform: 'uppercase', marginBottom: 8, opacity: .7 }}>{step.label}</div>
        <h3 style={{ fontFamily: 'Space Grotesk,sans-serif', fontWeight: 700, fontSize: 19, color: t.text, margin: '0 0 10px' }}>{step.title}</h3>
        <p style={{ fontFamily: 'DM Sans,sans-serif', fontSize: 13, color: t.textMute, lineHeight: 1.7, margin: 0 }}>{step.desc}</p>
      </div>
      <div style={{
        flex: '0 0 26px', width: 26, height: 26, borderRadius: '50%',
        background: `radial-gradient(circle,${step.color}20,transparent 70%)`,
        border: `1.5px solid ${step.color}`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontFamily: 'monospace', fontWeight: 700, fontSize: 10, color: step.color,
        zIndex: 1, marginTop: 4, flexShrink: 0,
        boxShadow: `0 0 14px ${step.color}30`,
      }}>
        {index + 1}
      </div>
      <div style={{ flex: '0 0 calc(50% - 32px)' }} />
    </div>
  );
}

// ─── Data ────────────────────────────────────────────────────────────────────
const FEATURES = [
  { iconKey: 'globe'     as const, title: 'Site Intelligence', color: '#c4a882', desc: 'Parcel analysis, FEMA flood zones, USGS seismic data, OSM neighbor constraints, terrain slope, and preliminary site-feasibility flags.' },
  { iconKey: 'building'  as const, title: 'Automated Massing', color: '#8fa898', desc: 'Three massing options (rectangle, L-shape, bar) generated from your parcel envelope, scored on cost, compactness, and daylight.' },
  { iconKey: 'blueprint' as const, title: 'Floor Plan Layout', color: '#c4a882', desc: 'Unit mix, corridor spine, stair core, and sub-room placement packed into the chosen massing for design-team review.' },
  { iconKey: 'bolt'      as const, title: 'MEP Routing',       color: '#d4943a', desc: 'Complete plumbing risers and branches, electrical panels and conduit runs, and HVAC duct layouts — all connected and code-aware.' },
  { iconKey: 'facade'    as const, title: 'Facade Design',     color: '#8fa898', desc: 'Windows sized and spaced per floor, dark frames, roof parapet — styled to match surrounding OSM building materials and colors.' },
  { iconKey: 'shield'    as const, title: 'Code Preflight',     color: '#c4a882', desc: 'A multi-code preliminary preflight reports egress, fire-safety, structural, energy, accessibility, and documentation findings without claiming permit approval.' },
];

const STEPS = [
  { label: 'Step 01', title: 'Drop a pin', color: '#c4a882', desc: 'Click anywhere on the map to select a parcel. Petronus fetches the site boundary, flood zone, seismic data, neighbor buildings, and terrain elevation automatically.' },
  { label: 'Step 02', title: 'Set parameters', color: '#8fa898', desc: 'Choose stories, unit count, structural system (wood / steel / concrete), HVAC type, and your priority — cost, speed, or daylight.' },
  { label: 'Step 03', title: 'Generate', color: '#c4a882', desc: 'Hit Generate. In under 30 seconds the pipeline runs: massing → floorplan → MEP → preliminary preflight → facade. All connected and modeled to scale.' },
  { label: 'Step 04', title: 'Review & export', color: '#d4943a', desc: 'Orbit the 3D model, toggle MEP layers, review preflight findings, pick your massing option, and export the concept model.' },
];
