'use client';
import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import dynamic from 'next/dynamic';
import { useAppStore } from '@/lib/store';
import ProjectWizard from '@/components/ui/ProjectWizard';
import IssuesPanel from '@/components/ui/IssuesPanel';
import MassingPicker from '@/components/ui/MassingPicker';
import AIChat from '@/components/ui/AIChat';

// Dynamic imports to avoid SSR issues with Three.js / MapLibre
const SiteMap = dynamic(() => import('@/components/map/SiteMap'), { ssr: false });
const BuildingViewer = dynamic(() => import('@/components/viewer/BuildingViewer'), { ssr: false });

type Tab = 'map' | '3d';
type RightTab = 'setup' | 'massing' | 'issues' | 'ai';

export default function HomePage() {
  const router = useRouter();
  const [mainTab, setMainTab] = useState<Tab>('map');
  const [rightTab, setRightTab] = useState<RightTab>('setup');
  const { buildingModel, selectedSite } = useAppStore();

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

        {/* Status */}
        <div className="flex items-center gap-2">
          {buildingModel ? (
            <div className="flex items-center gap-2 text-xs font-mono">
              <div className="w-2 h-2 rounded-full bg-[var(--accent-green)] animate-pulse" />
              <span className="text-[var(--accent-green)]">
                {buildingModel.rooms.length} rooms · {buildingModel.mep_elements.length} MEP elements
              </span>
            </div>
          ) : selectedSite ? (
            <div className="flex items-center gap-2 text-xs font-mono text-[var(--text-secondary)]">
              <div className="w-2 h-2 rounded-full bg-[var(--accent-cyan)]" />
              Site selected
            </div>
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
    </div>
  );
}
