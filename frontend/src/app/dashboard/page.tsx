'use client';
import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';

// ── Fake data ────────────────────────────────────────────────────────────────
const PROFILE = {
  name: 'Alex Chen', initials: 'AC',
  role: 'Principal Architect', company: 'Bay Area Development Group',
  location: 'San Francisco, CA', email: 'alex.chen@badg.io',
  member_since: 'January 2026', tier: 'Pro Beta',
};
const ACTIVITY_MONTHS = [
  { m: 'Sep', v: 1 }, { m: 'Oct', v: 2 }, { m: 'Nov', v: 1 },
  { m: 'Dec', v: 3 }, { m: 'Jan', v: 2 }, { m: 'Feb', v: 2 }, { m: 'Mar', v: 3 },
];
const STATUS_DATA = [
  { label: 'Generated', value: 8, color: '#00e5ff' },
  { label: 'In Review',  value: 2, color: '#ffb300' },
  { label: 'Exported',   value: 2, color: '#00ff88' },
];
const PROJECTS = [
  { id:1, name:'Fremont Infill — 4 Units',  addr:'37823 Fremont Blvd, Fremont CA',  date:'Mar 12',  stories:3, units:4,  sqft:3300, status:'generated', seismic:'D', flood:'X' },
  { id:2, name:'Oakland ADU Stack',          addr:'2210 Telegraph Ave, Oakland CA',   date:'Mar 8',   stories:2, units:2,  sqft:1840, status:'generated', seismic:'D', flood:'X' },
  { id:3, name:'San Jose Mixed-Use',         addr:'115 S Market St, San Jose CA',     date:'Feb 28',  stories:3, units:6,  sqft:5200, status:'review',    seismic:'D', flood:'AE' },
  { id:4, name:'Palo Alto Duplex',           addr:'488 High St, Palo Alto CA',        date:'Feb 15',  stories:2, units:2,  sqft:2100, status:'exported',   seismic:'C', flood:'X' },
  { id:5, name:'Berkeley 3-Unit Infill',     addr:'2801 Telegraph Ave, Berkeley CA',  date:'Feb 3',   stories:2, units:3,  sqft:2600, status:'exported',   seismic:'D', flood:'X' },
];
const FEED = [
  { icon:'⚡', text:'Generated Fremont Infill — 4 Units',  time:'2h ago',  color:'#00e5ff' },
  { icon:'✓',  text:'Exported Palo Alto Duplex to BIM',    time:'5 days',  color:'#00ff88' },
  { icon:'⚠',  text:'Review flagged: San Jose flood zone', time:'5 days',  color:'#ffb300' },
  { icon:'⚡', text:'Generated Oakland ADU Stack',          time:'7 days',  color:'#00e5ff' },
  { icon:'✓',  text:'Exported Berkeley 3-Unit Infill',     time:'40 days', color:'#00ff88' },
  { icon:'⚡', text:'Generated San Jose Mixed-Use',         time:'15 days', color:'#00e5ff' },
];

// ── Reusable card ────────────────────────────────────────────────────────────
function Card({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return (
    <div style={{
      background: '#0d1117', border: '1px solid rgba(255,255,255,0.07)',
      borderRadius: 16, padding: 24, ...style,
    }}>
      {children}
    </div>
  );
}
function CardTitle({ children, accent }: { children: React.ReactNode; accent?: string }) {
  return (
    <div style={{
      fontFamily: 'monospace', fontSize: 10, letterSpacing: '3px',
      textTransform: 'uppercase', color: accent || '#00e5ff',
      opacity: .7, marginBottom: 20,
    }}>{children}</div>
  );
}

// ── Bar chart ────────────────────────────────────────────────────────────────
function BarChart() {
  const max = Math.max(...ACTIVITY_MONTHS.map(d => d.v));
  const W = 320, H = 110, barW = 30, gap = (W - barW * ACTIVITY_MONTHS.length) / (ACTIVITY_MONTHS.length + 1);
  return (
    <svg width={W} height={H + 28} style={{ overflow: 'visible' }}>
      <defs>
        <linearGradient id="barGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#00e5ff" stopOpacity="0.9" />
          <stop offset="100%" stopColor="#00ff88" stopOpacity="0.4" />
        </linearGradient>
      </defs>
      {ACTIVITY_MONTHS.map((d, i) => {
        const x = gap + i * (barW + gap);
        const barH = (d.v / max) * H;
        const isLast = i === ACTIVITY_MONTHS.length - 1;
        return (
          <g key={d.m}>
            <rect x={x} y={H - barH} width={barW} height={barH} rx={4}
              fill={isLast ? 'url(#barGrad)' : 'rgba(0,229,255,0.18)'}
              stroke={isLast ? '#00e5ff' : 'rgba(0,229,255,0.25)'}
              strokeWidth={1}
            />
            {isLast && (
              <text x={x + barW / 2} y={H - barH - 6} textAnchor="middle"
                fill="#00e5ff" fontSize={10} fontFamily="monospace">{d.v}</text>
            )}
            <text x={x + barW / 2} y={H + 18} textAnchor="middle"
              fill={isLast ? '#c0c0d8' : '#4a4a66'} fontSize={10} fontFamily="monospace">{d.m}</text>
          </g>
        );
      })}
      {/* Grid lines */}
      {[1, 2, 3].map(v => (
        <line key={v} x1={0} y1={H - (v / max) * H} x2={W} y2={H - (v / max) * H}
          stroke="rgba(255,255,255,0.04)" strokeWidth={1} />
      ))}
    </svg>
  );
}

// ── Donut chart ──────────────────────────────────────────────────────────────
function DonutChart() {
  const total = STATUS_DATA.reduce((s, d) => s + d.value, 0);
  const R = 52, r = 34, cx = 70, cy = 70;
  let angle = -Math.PI / 2;
  const slices = STATUS_DATA.map(d => {
    const sweep = (d.value / total) * Math.PI * 2;
    const x1 = cx + R * Math.cos(angle), y1 = cy + R * Math.sin(angle);
    angle += sweep;
    const x2 = cx + R * Math.cos(angle), y2 = cy + R * Math.sin(angle);
    const mx1 = cx + r * Math.cos(angle - sweep), my1 = cy + r * Math.sin(angle - sweep);
    const mx2 = cx + r * Math.cos(angle), my2 = cy + r * Math.sin(angle);
    const large = sweep > Math.PI ? 1 : 0;
    return { ...d, path: `M${x1},${y1} A${R},${R},0,${large},1,${x2},${y2} L${mx2},${my2} A${r},${r},0,${large},0,${mx1},${my1} Z` };
  });
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 24 }}>
      <svg width={140} height={140}>
        {slices.map((s, i) => (
          <path key={i} d={s.path} fill={s.color} opacity={0.85} stroke="#0d1117" strokeWidth={2} />
        ))}
        <text x={cx} y={cy - 6} textAnchor="middle" fill="#f0f0f8" fontSize={22}
          fontFamily="Space Grotesk,sans-serif" fontWeight={700}>{total}</text>
        <text x={cx} y={cy + 12} textAnchor="middle" fill="#8888aa" fontSize={10}
          fontFamily="monospace">projects</text>
      </svg>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {STATUS_DATA.map(d => (
          <div key={d.label} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 10, height: 10, borderRadius: '50%', background: d.color, flexShrink: 0 }} />
            <span style={{ fontFamily: 'monospace', fontSize: 11, color: '#8888aa' }}>{d.label}</span>
            <span style={{ fontFamily: 'Space Grotesk,sans-serif', fontWeight: 700, fontSize: 14,
              color: d.color, marginLeft: 'auto', paddingLeft: 12 }}>{d.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Stat card ────────────────────────────────────────────────────────────────
function StatCard({ val, label, sub, color, spark }: {
  val: string; label: string; sub: string; color: string; spark?: number[];
}) {
  const max = spark ? Math.max(...spark) : 1;
  return (
    <Card style={{ padding: '20px 22px' }}>
      <div style={{ fontFamily: 'monospace', fontSize: 9, color: '#4a4a66', letterSpacing: '2px',
        textTransform: 'uppercase', marginBottom: 10 }}>{label}</div>
      <div style={{ fontFamily: 'Space Grotesk,sans-serif', fontWeight: 700, fontSize: 32,
        background: `linear-gradient(135deg,${color},${color}99)`,
        WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
        backgroundClip: 'text', marginBottom: 4 }}>{val}</div>
      <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#4a4a66', marginBottom: spark ? 14 : 0 }}>{sub}</div>
      {spark && (
        <svg width="100%" height={28} viewBox={`0 0 ${spark.length * 8} 28`} preserveAspectRatio="none">
          <polyline
            points={spark.map((v, i) => `${i * 8},${28 - (v / max) * 22}`).join(' ')}
            fill="none" stroke={color} strokeWidth={1.5} opacity={0.5}
          />
        </svg>
      )}
    </Card>
  );
}

// ── Status badge ─────────────────────────────────────────────────────────────
const STATUS_COLORS: Record<string, string> = { generated: '#00e5ff', review: '#ffb300', exported: '#00ff88' };
function Badge({ status }: { status: string }) {
  const c = STATUS_COLORS[status] || '#8888aa';
  return (
    <span style={{ fontFamily: 'monospace', fontSize: 9, color: c,
      background: `${c}18`, border: `1px solid ${c}30`,
      borderRadius: 5, padding: '2px 8px', letterSpacing: '1px', textTransform: 'uppercase' }}>
      {status}
    </span>
  );
}

// ── Main ─────────────────────────────────────────────────────────────────────
export default function DashboardPage() {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<'overview'|'projects'|'activity'>('overview');

  return (
    <div style={{ background: '#070b10', minHeight: '100vh', color: '#f0f0f8', fontFamily: 'DM Sans,sans-serif' }}>
      {/* Nav */}
      <nav style={{
        position: 'sticky', top: 0, zIndex: 50,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '14px 36px',
        background: 'rgba(7,11,16,0.85)', backdropFilter: 'blur(16px)',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button onClick={() => router.push('/')} style={{
            background: 'none', border: 'none', cursor: 'pointer', padding: '4px 8px',
            fontFamily: 'monospace', fontSize: 12, color: '#4a4a66',
            display: 'flex', alignItems: 'center', gap: 6,
          }}>← Back</button>
          <div style={{ width: 1, height: 16, background: 'rgba(255,255,255,0.08)' }} />
          <img src="/petronus.png" alt="" onClick={() => router.push('/')}
            style={{ width: 24, height: 24, borderRadius: 6, objectFit: 'cover', cursor: 'pointer' }} />
          <span style={{ fontFamily: 'Space Grotesk,sans-serif', fontWeight: 700, fontSize: 15,
            background: 'linear-gradient(135deg,#00e5ff,#00ff88)',
            WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', backgroundClip: 'text' }}>
            Dashboard
          </span>
        </div>
        <button onClick={() => router.push('/app')} style={{
          padding: '8px 20px', borderRadius: 8, fontFamily: 'monospace', fontSize: 12, fontWeight: 600,
          background: 'linear-gradient(135deg,rgba(0,229,255,0.15),rgba(0,255,136,0.1))',
          border: '1px solid rgba(0,229,255,0.3)', color: '#00e5ff', cursor: 'pointer',
        }}>
          Launch App →
        </button>
      </nav>

      <div style={{ maxWidth: 1200, margin: '0 auto', padding: '36px 36px 80px' }}>

        {/* Profile header */}
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 28, marginBottom: 36,
          padding: '28px 32px', borderRadius: 20,
          background: 'linear-gradient(135deg,rgba(0,229,255,0.04),rgba(0,255,136,0.02))',
          border: '1px solid rgba(0,229,255,0.1)' }}>
          {/* Avatar */}
          <div style={{
            width: 72, height: 72, borderRadius: 18, flexShrink: 0,
            background: 'linear-gradient(135deg,#00e5ff22,#7c3aed22)',
            border: '2px solid rgba(0,229,255,0.3)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: 'Space Grotesk,sans-serif', fontWeight: 700, fontSize: 22, color: '#00e5ff',
          }}>{PROFILE.initials}</div>
          <div style={{ flex: 1 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
              <h1 style={{ fontFamily: 'Space Grotesk,sans-serif', fontWeight: 700, fontSize: 24,
                margin: 0, color: '#f0f0f8' }}>{PROFILE.name}</h1>
              <span style={{ fontFamily: 'monospace', fontSize: 9, color: '#00e5ff',
                background: 'rgba(0,229,255,0.1)', border: '1px solid rgba(0,229,255,0.25)',
                borderRadius: 6, padding: '3px 8px', letterSpacing: '2px' }}>{PROFILE.tier}</span>
            </div>
            <div style={{ fontFamily: 'DM Sans,sans-serif', fontSize: 14, color: '#8888aa', marginBottom: 12 }}>
              {PROFILE.role} · {PROFILE.company}
            </div>
            <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
              {[
                { icon: '◎', text: PROFILE.location },
                { icon: '✉', text: PROFILE.email },
                { icon: '◷', text: `Member since ${PROFILE.member_since}` },
              ].map(item => (
                <div key={item.text} style={{ display: 'flex', alignItems: 'center', gap: 6,
                  fontFamily: 'monospace', fontSize: 11, color: '#4a6a7a' }}>
                  <span style={{ opacity: .6 }}>{item.icon}</span> {item.text}
                </div>
              ))}
            </div>
          </div>
          {/* Quick actions */}
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => router.push('/settings')} style={{
              padding: '8px 16px', borderRadius: 8, fontFamily: 'monospace', fontSize: 11,
              background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)',
              color: '#8888aa', cursor: 'pointer',
            }}>Settings</button>
          </div>
        </div>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 4, marginBottom: 28,
          background: 'rgba(255,255,255,0.03)', borderRadius: 10, padding: 4, width: 'fit-content' }}>
          {(['overview', 'projects', 'activity'] as const).map(tab => (
            <button key={tab} onClick={() => setActiveTab(tab)} style={{
              padding: '8px 20px', borderRadius: 7, fontFamily: 'monospace', fontSize: 12,
              cursor: 'pointer', border: 'none', transition: 'all .2s',
              background: activeTab === tab ? 'rgba(0,229,255,0.12)' : 'transparent',
              color: activeTab === tab ? '#00e5ff' : '#4a4a66',
              textTransform: 'capitalize',
            }}>{tab}</button>
          ))}
        </div>

        {/* ── Overview tab ── */}
        {activeTab === 'overview' && (
          <>
            {/* Stat cards */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4,1fr)', gap: 16, marginBottom: 24 }}>
              <StatCard val="12" label="Projects" sub="all time" color="#00e5ff"
                spark={[1,1,1,2,1,3,2,2,3]} />
              <StatCard val="847" label="Rooms Planned" sub="across all models" color="#00ff88"
                spark={[40,40,60,80,60,120,80,100,140]} />
              <StatCard val="624" label="Code Checks" sub="CBC + ASCE 7-22" color="#7c3aed"
                spark={[30,30,60,80,50,100,80,90,110]} />
              <StatCard val="28.4s" label="Avg Generation" sub="per full model" color="#ffb300"
                spark={[32,30,29,31,28,27,29,28,28]} />
            </div>

            {/* Charts row */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 16, marginBottom: 24 }}>
              <Card>
                <CardTitle>Projects per Month</CardTitle>
                <BarChart />
              </Card>
              <Card style={{ minWidth: 240 }}>
                <CardTitle>Project Status</CardTitle>
                <DonutChart />
              </Card>
            </div>

            {/* Recent projects quick view */}
            <Card>
              <CardTitle>Recent Projects</CardTitle>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {PROJECTS.slice(0, 3).map(p => (
                  <div key={p.id} style={{
                    display: 'flex', alignItems: 'center', gap: 16, padding: '12px 16px',
                    borderRadius: 10, background: 'rgba(255,255,255,0.02)',
                    border: '1px solid rgba(255,255,255,0.04)',
                  }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontFamily: 'Space Grotesk,sans-serif', fontWeight: 600,
                        fontSize: 14, color: '#c0c0d8', marginBottom: 3 }}>{p.name}</div>
                      <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#4a4a66' }}>{p.addr}</div>
                    </div>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      <span style={{ fontFamily: 'monospace', fontSize: 10, color: '#4a6a7a' }}>{p.stories}fl · {p.units}u · {p.sqft.toLocaleString()} sqft</span>
                      <Badge status={p.status} />
                      <span style={{ fontFamily: 'monospace', fontSize: 10, color: '#3a3a5a' }}>{p.date}</span>
                    </div>
                  </div>
                ))}
              </div>
              <button onClick={() => setActiveTab('projects')} style={{
                marginTop: 16, fontFamily: 'monospace', fontSize: 11, color: '#00e5ff',
                background: 'none', border: 'none', cursor: 'pointer', opacity: .7,
              }}>View all projects →</button>
            </Card>
          </>
        )}

        {/* ── Projects tab ── */}
        {activeTab === 'projects' && (
          <Card>
            <CardTitle>All Projects</CardTitle>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {PROJECTS.map(p => (
                <div key={p.id} style={{
                  display: 'grid', gridTemplateColumns: '1fr auto auto auto auto',
                  alignItems: 'center', gap: 20, padding: '16px 20px',
                  borderRadius: 12, background: 'rgba(255,255,255,0.02)',
                  border: '1px solid rgba(255,255,255,0.05)',
                  transition: 'border-color .2s',
                }}>
                  <div>
                    <div style={{ fontFamily: 'Space Grotesk,sans-serif', fontWeight: 600,
                      fontSize: 14, color: '#c0c0d8', marginBottom: 4 }}>{p.name}</div>
                    <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#4a4a66' }}>{p.addr}</div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div style={{ fontFamily: 'monospace', fontSize: 11, color: '#8888aa' }}>{p.stories} stories · {p.units} units</div>
                    <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#3a3a5a', marginTop: 2 }}>{p.sqft.toLocaleString()} sqft</div>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-end' }}>
                    <span style={{ fontFamily: 'monospace', fontSize: 9, color: p.seismic === 'D' ? '#ff9944' : '#00ff88',
                      background: p.seismic === 'D' ? 'rgba(255,153,68,0.1)' : 'rgba(0,255,136,0.1)',
                      border: `1px solid ${p.seismic === 'D' ? 'rgba(255,153,68,0.3)' : 'rgba(0,255,136,0.3)'}`,
                      borderRadius: 4, padding: '2px 6px' }}>SDC {p.seismic}</span>
                    <span style={{ fontFamily: 'monospace', fontSize: 9,
                      color: p.flood !== 'X' ? '#ff4444' : '#4a4a66',
                      background: p.flood !== 'X' ? 'rgba(255,68,68,0.1)' : 'transparent',
                      border: p.flood !== 'X' ? '1px solid rgba(255,68,68,0.3)' : '1px solid transparent',
                      borderRadius: 4, padding: '2px 6px' }}>Flood {p.flood}</span>
                  </div>
                  <Badge status={p.status} />
                  <span style={{ fontFamily: 'monospace', fontSize: 10, color: '#3a3a5a', minWidth: 48, textAlign: 'right' }}>{p.date}</span>
                </div>
              ))}
            </div>
          </Card>
        )}

        {/* ── Activity tab ── */}
        {activeTab === 'activity' && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 16 }}>
            <Card>
              <CardTitle>Activity Feed</CardTitle>
              <div style={{ position: 'relative' }}>
                <div style={{ position: 'absolute', left: 18, top: 0, bottom: 0,
                  width: 1, background: 'rgba(255,255,255,0.05)' }} />
                {FEED.map((f, i) => (
                  <div key={i} style={{ display: 'flex', gap: 16, marginBottom: 24, position: 'relative' }}>
                    <div style={{
                      width: 36, height: 36, borderRadius: '50%', flexShrink: 0,
                      background: `${f.color}18`, border: `1px solid ${f.color}30`,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 14, zIndex: 1,
                    }}>{f.icon}</div>
                    <div style={{ paddingTop: 6 }}>
                      <div style={{ fontFamily: 'DM Sans,sans-serif', fontSize: 14, color: '#c0c0d8', marginBottom: 3 }}>{f.text}</div>
                      <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#3a3a5a' }}>{f.time} ago</div>
                    </div>
                  </div>
                ))}
              </div>
            </Card>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              <Card>
                <CardTitle accent="#00ff88">This Month</CardTitle>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  {[
                    { label: 'Projects generated', val: '3', color: '#00e5ff' },
                    { label: 'Rooms planned', val: '214', color: '#00ff88' },
                    { label: 'Code checks run', val: '156', color: '#7c3aed' },
                    { label: 'Avg generation time', val: '27.1s', color: '#ffb300' },
                  ].map(row => (
                    <div key={row.label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontFamily: 'monospace', fontSize: 11, color: '#4a4a66' }}>{row.label}</span>
                      <span style={{ fontFamily: 'Space Grotesk,sans-serif', fontWeight: 700, fontSize: 16, color: row.color }}>{row.val}</span>
                    </div>
                  ))}
                </div>
              </Card>
              <Card>
                <CardTitle accent="#7c3aed">Compliance Summary</CardTitle>
                {[
                  { label: 'CBC checks passed', pct: 94, color: '#00ff88' },
                  { label: 'Flood zone warnings', pct: 17, color: '#ffb300' },
                  { label: 'Seismic SDC D sites', pct: 83, color: '#f472b6' },
                ].map(row => (
                  <div key={row.label} style={{ marginBottom: 14 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                      <span style={{ fontFamily: 'monospace', fontSize: 10, color: '#4a4a66' }}>{row.label}</span>
                      <span style={{ fontFamily: 'monospace', fontSize: 10, color: row.color }}>{row.pct}%</span>
                    </div>
                    <div style={{ height: 4, background: 'rgba(255,255,255,0.05)', borderRadius: 2 }}>
                      <div style={{ height: '100%', width: `${row.pct}%`, background: row.color,
                        borderRadius: 2, opacity: .7 }} />
                    </div>
                  </div>
                ))}
              </Card>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
