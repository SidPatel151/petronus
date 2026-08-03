'use client';
import { useState, useEffect, useMemo } from 'react';
import { useRouter } from 'next/navigation';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

function fmtDate(iso: string) {
  if (!iso) return '';
  try {
    const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  } catch { return iso.slice(0, 10); }
}

const SC: Record<string, string> = { generated: '#00e5ff', review: '#ffb300', exported: '#00ff88', created: '#8888aa' };

function Badge({ status }: { status: string }) {
  const c = SC[status] || '#8888aa';
  return (
    <span className="font-mono text-[9px] rounded px-2 py-0.5 uppercase tracking-widest"
      style={{ color: c, background: `${c}18`, border: `1px solid ${c}40` }}>
      {status}
    </span>
  );
}

function Stat({ label, val, color }: { label: string; val: string | number; color: string }) {
  return (
    <div className="rounded-2xl p-5" style={{ background: '#0d1117', border: '1px solid rgba(255,255,255,0.07)' }}>
      <div className="font-mono text-[9px] uppercase tracking-widest mb-2" style={{ color: '#4a4a66' }}>{label}</div>
      <div className="font-display font-bold text-3xl" style={{ color }}>{val}</div>
    </div>
  );
}

export default function DashboardPage() {
  const router = useRouter();
  const [tab, setTab] = useState<'overview' | 'projects' | 'activity'>('overview');
  const [projects, setProjects] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');

  useEffect(() => {
    fetch(`${API_BASE}/api/projects/`)
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(data => setProjects(Array.isArray(data) ? data : []))
      .catch(e => setErr(`Could not reach API (${e})`))
      .finally(() => setLoading(false));
  }, []);

  const stats = useMemo(() => ({
    total:     projects.length,
    sqft:      projects.reduce((s, p) => s + (p.sqft || 0), 0).toLocaleString(),
    generated: projects.filter(p => p.status === 'generated').length,
    sdcD:      projects.filter(p => p.seismic === 'D').length,
  }), [projects]);

  const navBtn = 'font-mono text-xs px-5 py-2 rounded-lg border transition-colors cursor-pointer';

  return (
    <div className="min-h-screen" style={{ background: '#070b10', color: '#f0f0f8' }}>

      {/* ── Nav ── */}
      <nav className="sticky top-0 z-50 flex items-center justify-between px-9 py-3.5"
        style={{ background: 'rgba(7,11,16,0.9)', backdropFilter: 'blur(12px)', borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
        <div className="flex items-center gap-3">
          <button onClick={() => router.push('/')} className="font-mono text-xs cursor-pointer"
            style={{ background: 'none', border: 'none', color: '#4a4a66' }}>← Back</button>
          <div style={{ width: 1, height: 16, background: 'rgba(255,255,255,0.08)' }} />
          <span className="font-display font-bold text-base"
            style={{ background: 'linear-gradient(135deg,#00e5ff,#00ff88)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', backgroundClip: 'text' }}>
            Dashboard
          </span>
        </div>
        <button onClick={() => router.push('/app')} className={navBtn}
          style={{ background: 'rgba(0,229,255,0.08)', borderColor: 'rgba(0,229,255,0.3)', color: '#00e5ff' }}>
          Launch App →
        </button>
      </nav>

      <div className="max-w-5xl mx-auto px-9 py-9 pb-20">

        {/* ── Profile strip ── */}
        <div className="flex items-center gap-6 rounded-2xl px-8 py-6 mb-8"
          style={{ background: 'rgba(0,229,255,0.03)', border: '1px solid rgba(0,229,255,0.1)' }}>
          <div className="w-14 h-14 rounded-2xl flex items-center justify-center font-display font-bold text-xl flex-shrink-0"
            style={{ background: 'rgba(0,229,255,0.1)', border: '2px solid rgba(0,229,255,0.25)', color: '#00e5ff' }}>
            AC
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-3 mb-1">
              <span className="font-display font-bold text-lg">Alex Chen</span>
              <span className="font-mono text-[9px] rounded px-2 py-0.5 tracking-widest"
                style={{ color: '#00e5ff', background: 'rgba(0,229,255,0.1)', border: '1px solid rgba(0,229,255,0.25)' }}>PRO BETA</span>
            </div>
            <div className="font-mono text-xs" style={{ color: '#8888aa' }}>
              Principal Architect · Bay Area Development Group
            </div>
          </div>
          <button onClick={() => router.push('/settings')} className={navBtn}
            style={{ background: 'rgba(255,255,255,0.03)', borderColor: 'rgba(255,255,255,0.08)', color: '#8888aa' }}>
            Settings
          </button>
        </div>

        {/* ── Tabs ── */}
        <div className="flex gap-1 mb-7 rounded-xl p-1 w-fit" style={{ background: 'rgba(255,255,255,0.03)' }}>
          {(['overview', 'projects', 'activity'] as const).map(t => (
            <button key={t} onClick={() => setTab(t)}
              className="px-5 py-2 rounded-lg font-mono text-xs capitalize cursor-pointer border-none transition-colors"
              style={{
                background: tab === t ? 'rgba(0,229,255,0.12)' : 'transparent',
                color: tab === t ? '#00e5ff' : '#4a4a66',
              }}>
              {t}
            </button>
          ))}
        </div>

        {/* ── Overview ── */}
        {tab === 'overview' && (
          <div className="flex flex-col gap-6">
            <div className="grid grid-cols-4 gap-4">
              <Stat label="Total Projects" val={loading ? '…' : stats.total} color="#00e5ff" />
              <Stat label="Sqft Planned"   val={loading ? '…' : stats.sqft}  color="#00ff88" />
              <Stat label="Generated"      val={loading ? '…' : stats.generated} color="#ffb300" />
              <Stat label="SDC-D Sites"    val={loading ? '…' : stats.sdcD} color="#f472b6" />
            </div>

            {/* Recent projects */}
            <div className="rounded-2xl p-6" style={{ background: '#0d1117', border: '1px solid rgba(255,255,255,0.07)' }}>
              <div className="font-mono text-[10px] uppercase tracking-widest mb-5" style={{ color: '#00e5ff', opacity: .7 }}>Recent Projects</div>
              {err && <div className="font-mono text-xs text-red-400 mb-3">{err}</div>}
              {loading ? (
                <div className="font-mono text-xs" style={{ color: '#4a4a66' }}>Loading…</div>
              ) : projects.length === 0 ? (
                <div className="font-mono text-xs" style={{ color: '#4a4a66' }}>
                  No projects saved yet — generate a building in the app and click ↓ Save.
                </div>
              ) : (
                <div className="flex flex-col gap-2">
                  {projects.slice(0, 4).map(p => (
                    <div key={p.id} className="flex items-center gap-4 rounded-xl px-4 py-3"
                      style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.04)' }}>
                      <div className="flex-1 min-w-0">
                        <div className="font-display font-semibold text-sm truncate" style={{ color: '#c0c0d8' }}>{p.name}</div>
                        <div className="font-mono text-[10px] truncate" style={{ color: '#4a4a66' }}>{p.address}</div>
                      </div>
                      <div className="font-mono text-[10px] shrink-0" style={{ color: '#4a6a7a' }}>
                        {p.stories > 0 ? `${p.stories} fl` : ''}{p.sqft > 0 ? ` · ${p.sqft.toLocaleString()} sqft` : ''}
                      </div>
                      <Badge status={p.status} />
                      <span className="font-mono text-[10px] shrink-0" style={{ color: '#3a3a5a' }}>{fmtDate(p.updated_at)}</span>
                      <button onClick={() => router.push(`/app?load=${p.id}`)}
                        className="font-mono text-[10px] px-2.5 py-1 rounded-md border shrink-0 cursor-pointer transition-colors"
                        style={{ background: 'rgba(0,229,255,0.08)', borderColor: 'rgba(0,229,255,0.25)', color: '#00e5ff' }}>
                        Open →
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <button onClick={() => setTab('projects')}
                className="mt-4 font-mono text-[11px] cursor-pointer"
                style={{ background: 'none', border: 'none', color: '#00e5ff', opacity: .7 }}>
                View all →
              </button>
            </div>
          </div>
        )}

        {/* ── My Projects ── */}
        {tab === 'projects' && (
          <div className="rounded-2xl p-6" style={{ background: '#0d1117', border: '1px solid rgba(255,255,255,0.07)' }}>
            <div className="font-mono text-[10px] uppercase tracking-widest mb-5" style={{ color: '#00e5ff', opacity: .7 }}>My Projects</div>
            {err && <div className="font-mono text-xs text-red-400 mb-3">{err}</div>}
            {loading ? (
              <div className="font-mono text-xs" style={{ color: '#4a4a66' }}>Loading…</div>
            ) : projects.length === 0 ? (
              <div className="text-center py-10">
                <div className="font-mono text-xs mb-2" style={{ color: '#4a4a66' }}>No projects saved yet.</div>
                <button onClick={() => router.push('/app')}
                  className="mt-2 font-mono text-xs px-5 py-2 rounded-lg border cursor-pointer"
                  style={{ background: 'rgba(0,229,255,0.08)', borderColor: 'rgba(0,229,255,0.3)', color: '#00e5ff' }}>
                  Open App to Generate →
                </button>
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                {projects.map(p => (
                  <div key={p.id} className="grid items-center gap-4 rounded-xl px-5 py-4"
                    style={{
                      gridTemplateColumns: '1fr 130px 72px 72px 56px 64px',
                      background: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)',
                    }}>
                    <div className="min-w-0">
                      <div className="font-display font-semibold text-sm truncate" style={{ color: '#c0c0d8' }}>{p.name}</div>
                      <div className="font-mono text-[10px] truncate" style={{ color: '#4a4a66' }}>{p.address || '—'}</div>
                    </div>
                    <div className="font-mono text-[11px]" style={{ color: '#8888aa' }}>
                      {p.stories > 0 ? `${p.stories} fl` : '—'} · {p.sqft > 0 ? `${p.sqft.toLocaleString()} sqft` : '—'}
                    </div>
                    <div className="font-mono text-[9px] rounded px-1.5 py-0.5 text-center"
                      style={{
                        color: p.seismic === 'D' ? '#ff9944' : '#00ff88',
                        background: p.seismic === 'D' ? 'rgba(255,153,68,0.1)' : 'rgba(0,255,136,0.1)',
                        border: `1px solid ${p.seismic === 'D' ? 'rgba(255,153,68,0.3)' : 'rgba(0,255,136,0.3)'}`,
                      }}>
                      SDC {p.seismic || 'D'}
                    </div>
                    <Badge status={p.status} />
                    <span className="font-mono text-[10px] text-right" style={{ color: '#3a3a5a' }}>{fmtDate(p.updated_at)}</span>
                    <button onClick={() => router.push(`/app?load=${p.id}`)}
                      className="font-mono text-[10px] px-2.5 py-1 rounded-md border cursor-pointer transition-colors text-center"
                      style={{ background: 'rgba(0,229,255,0.08)', borderColor: 'rgba(0,229,255,0.25)', color: '#00e5ff' }}>
                      Open →
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Activity ── */}
        {tab === 'activity' && (
          <div className="rounded-2xl p-6" style={{ background: '#0d1117', border: '1px solid rgba(255,255,255,0.07)' }}>
            <div className="font-mono text-[10px] uppercase tracking-widest mb-5" style={{ color: '#00e5ff', opacity: .7 }}>Activity</div>
            {loading ? (
              <div className="font-mono text-xs" style={{ color: '#4a4a66' }}>Loading…</div>
            ) : projects.length === 0 ? (
              <div className="font-mono text-xs" style={{ color: '#4a4a66' }}>No activity yet.</div>
            ) : (
              <div className="flex flex-col gap-4">
                {projects.slice(0, 8).map((p, i) => (
                  <div key={i} className="flex items-start gap-4">
                    <div className="w-8 h-8 rounded-full flex items-center justify-center text-sm flex-shrink-0"
                      style={{ background: 'rgba(0,229,255,0.1)', border: '1px solid rgba(0,229,255,0.25)' }}>
                      ⚡
                    </div>
                    <div>
                      <div className="text-sm" style={{ color: '#c0c0d8' }}>
                        {p.status === 'generated' ? 'Generated' : 'Saved'} <strong>{p.name}</strong>
                      </div>
                      <div className="font-mono text-[10px] mt-0.5" style={{ color: '#3a3a5a' }}>{fmtDate(p.updated_at)}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
