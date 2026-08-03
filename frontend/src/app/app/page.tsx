'use client';
import { useState, useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import dynamic from 'next/dynamic';
import { useAppStore } from '@/lib/store';
import ProjectWizard from '@/components/ui/ProjectWizard';
import IssuesPanel from '@/components/ui/IssuesPanel';
import MassingPicker from '@/components/ui/MassingPicker';
import AIChat from '@/components/ui/AIChat';
import api from '@/lib/api';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// Dynamic imports to avoid SSR issues with Three.js / MapLibre
const SiteMap = dynamic(() => import('@/components/map/SiteMap'), { ssr: false });
const BuildingViewer = dynamic(() => import('@/components/viewer/BuildingViewer'), { ssr: false });

type Tab = 'map' | '3d';
type RightTab = 'setup' | 'massing' | 'issues' | 'ai';

function AppContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [mainTab, setMainTab] = useState<Tab>('map');
  const [rightTab, setRightTab] = useState<RightTab>('setup');
  const [saveModal, setSaveModal] = useState(false);
  const [saveName, setSaveName] = useState('');
  const [saving, setSaving] = useState(false);
  const [savedToast, setSavedToast] = useState(false);
  const [loadingProject, setLoadingProject] = useState(false);
  const {
    buildingModel, selectedSite, spec,
    setBuildingModel, setSelectedSite, setSiteContext,
    setInfrastructure, setNeighborConstraints, setFeasibilityData, setDrawnParcel,
    updateSpec,
  } = useAppStore();

  // Load project from ?load=ID query param (coming from dashboard)
  useEffect(() => {
    const loadId = searchParams.get('load');
    if (!loadId) return;
    setLoadingProject(true);
    fetch(`${API_BASE}/api/projects/${loadId}`)
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(project => {
        if (project.spec) updateSpec(project.spec);
        if (project.building_model) {
          setBuildingModel(project.building_model);
          const centroid = project.building_model?.site_context?.centroid;
          if (centroid) {
            setSelectedSite({
              lat: centroid[1] ?? centroid.lat,
              lon: centroid[0] ?? centroid.lon,
              address: project.name || '',
            } as any);
          }
          setMainTab('3d');
          setRightTab('issues');
        }
      })
      .catch(e => console.error('Failed to load project', e))
      .finally(() => setLoadingProject(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSave = async () => {
    if (!buildingModel || !saveName.trim()) return;
    setSaving(true);
    try {
      const addr = (selectedSite as any)?.address || '';
      // Persist the complete generated model so reopening a project restores the
      // same architecture, structure, MEP, issues, and render geometry.
      const savedSpec = (buildingModel as any).spec || spec;
      await api.saveProject(saveName.trim(), addr, savedSpec, buildingModel);
      setSaveModal(false);
      setSaveName('');
      setSavedToast(true);
      setTimeout(() => setSavedToast(false), 2500);
    } catch (e) {
      console.error('Save failed', e);
    } finally {
      setSaving(false);
    }
  };

  const handleNewSite = () => {
    setBuildingModel(null);
    setSelectedSite(null);
    setSiteContext(null);
    setInfrastructure(null);
    setNeighborConstraints(null);
    setFeasibilityData(null);
    setDrawnParcel(null);
    setMainTab('map');
    setRightTab('setup');
  };

  const handleRedesign = () => {
    setBuildingModel(null);
    setRightTab('setup');
  };

  useEffect(() => {
    document.documentElement.classList.add('app-page');
    document.body.classList.add('app-page');
    return () => {
      document.documentElement.classList.remove('app-page');
      document.body.classList.remove('app-page');
    };
  }, []);

  return (
    <div className="flex flex-col h-screen bg-[var(--surface-0)]">
      {loadingProject && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 99999,
          background: 'rgba(7,11,16,0.85)', backdropFilter: 'blur(8px)',
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 16,
        }}>
          <div style={{ width: 40, height: 40, border: '3px solid rgba(0,229,255,0.2)', borderTopColor: '#00e5ff', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
          <div style={{ fontFamily: 'monospace', fontSize: 12, color: '#00e5ff', letterSpacing: '2px' }}>LOADING PROJECT…</div>
        </div>
      )}

      {/* Top bar */}
      <header className="flex-shrink-0 flex items-center justify-between px-5 py-3 border-b border-[var(--border)] bg-[var(--surface-1)]">
        <div className="flex items-center gap-3 cursor-pointer" onClick={() => router.push('/')}>
          <img src="/petronus.png" alt="Petronus" className="w-7 h-7 rounded-lg object-cover" />
          <div>
            <div className="font-display font-semibold text-sm text-[var(--text-primary)] text-glow-cyan">
              Petronus
            </div>
            <div className="text-[10px] font-mono text-[var(--text-secondary)]">
              California · Multi-family Residential
            </div>
          </div>
        </div>

        {/* Main view tabs */}
        <div className="flex items-center gap-1 bg-[var(--surface-2)] rounded-lg p-1">
          {([['map', '🗺 Site Map'], ['3d', '🏢 3D Model']] as [Tab, string][]).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setMainTab(key)}
              className="px-4 py-1.5 rounded-md text-xs font-mono transition-all"
              style={{
                background: mainTab === key ? 'var(--surface-4)' : 'transparent',
                color: mainTab === key ? 'var(--accent-cyan)' : 'var(--text-secondary)',
                border: mainTab === key ? '1px solid var(--border)' : '1px solid transparent',
              }}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Status + reset actions */}
        <div className="flex items-center gap-2">
          {buildingModel ? (
            <>
              <div className="flex items-center gap-2 text-xs font-mono">
                <div className="w-2 h-2 rounded-full bg-[var(--accent-green)] animate-pulse" />
                <span className="text-[var(--accent-green)]">
                  {buildingModel.rooms.length} rooms · {buildingModel.mep_elements.length} MEP
                </span>
              </div>
              <button
                onClick={handleRedesign}
                title="Keep this site, clear the model and tweak settings"
                className="text-xs font-mono px-2.5 py-1 rounded-md border transition-all"
                style={{ borderColor: 'var(--border)', color: 'var(--text-secondary)', background: 'var(--surface-2)' }}
              >
                ↺ Redesign
              </button>
              <button
                onClick={() => { setSaveName(''); setSaveModal(true); }}
                title="Save this project"
                className="text-xs font-mono px-2.5 py-1 rounded-md border transition-all"
                style={{ borderColor: 'var(--accent-green)', color: 'var(--accent-green)', background: 'var(--surface-2)' }}
              >
                ↓ Save
              </button>
              <button
                onClick={handleNewSite}
                title="Pick a new parcel and start fresh"
                className="text-xs font-mono px-2.5 py-1 rounded-md border transition-all"
                style={{ borderColor: 'var(--accent-cyan)', color: 'var(--accent-cyan)', background: 'var(--surface-2)' }}
              >
                + New Site
              </button>
            </>
          ) : selectedSite ? (
            <>
              <div className="flex items-center gap-2 text-xs font-mono text-[var(--text-secondary)]">
                <div className="w-2 h-2 rounded-full bg-[var(--accent-cyan)]" />
                Site selected
              </div>
              <button
                onClick={handleNewSite}
                title="Pick a different parcel"
                className="text-xs font-mono px-2.5 py-1 rounded-md border transition-all"
                style={{ borderColor: 'var(--border)', color: 'var(--text-secondary)', background: 'var(--surface-2)' }}
              >
                Change Parcel
              </button>
            </>
          ) : (
            <div className="text-xs font-mono text-[var(--text-secondary)]">No site selected</div>
          )}
        </div>
      </header>

      {/* Main content */}
      <div className="flex flex-1 min-h-0">

        {/* Main view */}
        <div className="flex-1 min-w-0 relative">
          <div className={mainTab === 'map' ? 'absolute inset-0' : 'hidden'}>
            <SiteMap />
          </div>
          <div className={mainTab === '3d' ? 'absolute inset-0' : 'hidden'}>
            <BuildingViewer />
          </div>
        </div>

        {/* Right panel */}
        <div className="w-80 flex-shrink-0 flex flex-col border-l border-[var(--border)] bg-[var(--surface-1)]">

          {/* Right tab bar */}
          <div className="flex border-b border-[var(--border)] bg-[var(--surface-2)]">
            {([
              ['setup', 'Setup'],
              ['massing', 'Massing'],
              ['issues', `Issues${buildingModel?.issues?.length ? ` (${buildingModel.issues.length})` : ''}`],
              ['ai', '✦ AI'],
            ] as [RightTab, string][]).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setRightTab(key)}
                className="flex-1 py-2.5 text-xs font-mono transition-colors"
                style={{
                  color: rightTab === key ? 'var(--accent-cyan)' : 'var(--text-secondary)',
                  borderBottom: rightTab === key ? '2px solid var(--accent-cyan)' : '2px solid transparent',
                  background: rightTab === key ? 'var(--surface-1)' : 'transparent',
                }}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Right panel content */}
          <div className="flex-1 min-h-0 overflow-hidden">
            {rightTab === 'setup' && (
              <div className="h-full panel overflow-hidden rounded-none border-0">
                <ProjectWizard />
              </div>
            )}
            {rightTab === 'massing' && (
              <div className="h-full overflow-y-auto">
                {buildingModel ? (
                  <MassingPicker />
                ) : (
                  <div className="p-4 text-xs font-mono text-[var(--text-secondary)] italic">
                    Generate a building first
                  </div>
                )}
              </div>
            )}
            {rightTab === 'issues' && (
              <div className="h-full overflow-hidden">
                <IssuesPanel />
              </div>
            )}
            {rightTab === 'ai' && (
              <div className="h-full overflow-hidden">
                <AIChat />
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Save Project Modal ─────────────────────────────────────────────── */}
      {saveModal && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 9999,
          background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(6px)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }} onClick={() => setSaveModal(false)}>
          <div style={{
            background: '#0d1117', border: '1px solid rgba(0,255,136,0.25)',
            borderRadius: 16, padding: '28px 32px', width: 380, boxShadow: '0 24px 64px rgba(0,0,0,0.6)',
          }} onClick={e => e.stopPropagation()}>
            <div style={{ fontFamily: 'monospace', fontSize: 10, letterSpacing: '3px',
              textTransform: 'uppercase', color: '#00ff88', opacity: .7, marginBottom: 16 }}>
              Save Project
            </div>
            <input
              autoFocus
              placeholder="Project name…"
              value={saveName}
              onChange={e => setSaveName(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') handleSave(); if (e.key === 'Escape') setSaveModal(false); }}
              style={{
                width: '100%', background: 'rgba(255,255,255,0.04)',
                border: '1px solid rgba(255,255,255,0.12)', borderRadius: 8,
                padding: '10px 14px', color: '#f0f0f8', fontFamily: 'DM Sans,sans-serif',
                fontSize: 14, marginBottom: 20, boxSizing: 'border-box', outline: 'none',
              }}
            />
            <div style={{ display: 'flex', gap: 10 }}>
              <button onClick={() => setSaveModal(false)} style={{
                flex: 1, padding: '10px 0', borderRadius: 8, fontFamily: 'monospace', fontSize: 12,
                background: 'transparent', border: '1px solid rgba(255,255,255,0.08)',
                color: '#4a4a66', cursor: 'pointer',
              }}>Cancel</button>
              <button onClick={handleSave} disabled={!saveName.trim() || saving} style={{
                flex: 2, padding: '10px 0', borderRadius: 8, fontFamily: 'monospace', fontSize: 12,
                background: saveName.trim() ? 'rgba(0,255,136,0.15)' : 'rgba(255,255,255,0.04)',
                border: `1px solid ${saveName.trim() ? 'rgba(0,255,136,0.4)' : 'rgba(255,255,255,0.06)'}`,
                color: saveName.trim() ? '#00ff88' : '#3a3a5a', cursor: saveName.trim() ? 'pointer' : 'default',
              }}>{saving ? 'Saving…' : 'Save Project'}</button>
            </div>
          </div>
        </div>
      )}

      {/* ── Saved toast ───────────────────────────────────────────────────── */}
      {savedToast && (
        <div style={{
          position: 'fixed', bottom: 24, right: 24, zIndex: 9999,
          background: 'rgba(0,255,136,0.12)', border: '1px solid rgba(0,255,136,0.35)',
          borderRadius: 10, padding: '10px 20px',
          fontFamily: 'monospace', fontSize: 12, color: '#00ff88',
        }}>
          Project saved
        </div>
      )}
    </div>
  );
}

export default function HomePage() {
  return (
    <Suspense>
      <AppContent />
    </Suspense>
  );
}
