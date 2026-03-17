'use client';
import { useState, useRef, useEffect } from 'react';
import { useAppStore } from '@/lib/store';
import api from '@/lib/api';

const SUGGESTIONS = [
  'Make it 3 stories with an L-shape',
  'Switch to steel framing',
  'Optimize for natural daylight',
  'Add 8 residential units',
  'What are the seismic requirements here?',
  'Explain the compliance issues',
];

export default function AIChat() {
  const {
    chatMessages, addChatMessage,
    siteContext, buildingModel, clickedBuilding,
    spec, updateSpec, setBuildingModel, selectedSite,
  } = useAppStore();
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages, loading, regenerating]);

  const send = async (text?: string) => {
    const content = text || input.trim();
    if (!content || loading) return;
    setInput('');

    const userMsg = { role: 'user' as const, content };
    addChatMessage(userMsg);
    setLoading(true);

    try {
      const history = [...chatMessages, userMsg];
      const { reply, spec_patch } = await api.chat(
        history.map(m => ({ role: m.role, content: m.content })),
        siteContext,
        buildingModel,
        clickedBuilding,
      );

      addChatMessage({ role: 'assistant', content: reply });

      // If Claude returned spec changes, apply them and regenerate
      if (spec_patch && Object.keys(spec_patch).length > 0 && selectedSite) {
        setLoading(false);
        setRegenerating(true);

        // Apply patch to spec
        const { shape_hint, ...specChanges } = spec_patch;
        updateSpec(specChanges);

        // Build full spec with patches applied
        const fullSpec = {
          region_country: 'US', region_state: 'CA',
          occupancy: 'MultiFamilyResidential', permit_set: false,
          stories: spec.stories || 2,
          floor_to_floor_height_ft: spec.floor_to_floor_height_ft || 10.0,
          structural_system: spec.structural_system || 'wood',
          hvac_preference: spec.hvac_preference || 'mini_split',
          parking_strategy: spec.parking_strategy || 'ignore',
          priority: spec.priority || 'cost',
          target_gross_area_sqft: spec.target_gross_area_sqft || 8000,
          unit_count: spec.unit_count || null,
          ...specChanges,
          site: {
            latlon: { lat: selectedSite.lat, lon: selectedSite.lon },
            address: null,
            parcel_polygon: siteContext?.parcel_polygon || null,
          },
        };

        try {
          const result = await api.quickGenerate(fullSpec);
          if (result.result) {
            setBuildingModel(result.result);
            addChatMessage({
              role: 'assistant',
              content: `Done — building regenerated with your changes. Check the 3D model tab.`,
            });
          }
        } catch {
          addChatMessage({ role: 'assistant', content: 'I updated the settings but the regeneration failed. Try pressing Generate manually.' });
        } finally {
          setRegenerating(false);
        }
        return;
      }
    } catch {
      addChatMessage({ role: 'assistant', content: 'Could not reach the AI. Check that the backend is running.' });
    } finally {
      setLoading(false);
    }
  };

  const busy = loading || regenerating;

  return (
    <div className="flex flex-col h-full">
      {/* Messages */}
      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3">
        {chatMessages.length === 0 && (
          <div className="space-y-3">
            <div className="text-xs font-mono text-[var(--text-secondary)] text-center pt-4 pb-2">
              Describe changes or ask questions — I can rebuild the model directly.
            </div>
            <div className="space-y-1.5">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="w-full text-left text-xs font-mono px-3 py-2 rounded-lg border border-[var(--border)] text-[var(--text-secondary)] hover:text-[var(--accent-cyan)] hover:border-[var(--accent-cyan)] transition-colors bg-[var(--surface-2)]"
                >
                  {s}
                </button>
              ))}
            </div>

            {siteContext && (
              <div className="bg-[var(--surface-2)] rounded-lg p-3 space-y-1.5">
                <div className="text-[10px] font-mono text-[var(--text-secondary)] uppercase tracking-wider mb-1">Live Site Data</div>
                {[
                  `Seismic SDC ${siteContext.seismic_category} · USGS ASCE 7-22`,
                  `Wind ${siteContext.wind_speed_mph} mph · ASCE 7-22`,
                  siteContext.hazard_detail?.current_weather?.temp_f
                    ? `${siteContext.hazard_detail.current_weather.temp_f}°F · ${siteContext.hazard_detail.current_weather.description}`
                    : null,
                  `Flood zone ${siteContext.flood_zone || 'X'} · FEMA`,
                ].filter(Boolean).map((line) => (
                  <div key={line} className="flex items-center gap-2 text-xs font-mono">
                    <div className="w-1.5 h-1.5 rounded-full bg-[var(--accent-green)] flex-shrink-0" />
                    <span className="text-[var(--text-secondary)]">{line}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {chatMessages.map((msg, i) => (
          <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className="max-w-[85%] rounded-lg px-3 py-2 text-xs font-mono leading-relaxed"
              style={{
                background: msg.role === 'user' ? 'var(--accent-cyan)' : 'var(--surface-3)',
                color: msg.role === 'user' ? '#0a0a0f' : 'var(--text-primary)',
              }}
            >
              {msg.role === 'assistant' && (
                <div className="text-[9px] text-[var(--accent-cyan)] uppercase tracking-wider mb-1 opacity-70">Petronus AI</div>
              )}
              <div style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>
            </div>
          </div>
        ))}

        {loading && !regenerating && (
          <div className="flex justify-start">
            <div className="bg-[var(--surface-3)] rounded-lg px-3 py-2 text-xs font-mono text-[var(--text-secondary)] animate-pulse">
              Thinking…
            </div>
          </div>
        )}

        {regenerating && (
          <div className="flex justify-start">
            <div className="bg-[var(--surface-3)] rounded-lg px-3 py-2 text-xs font-mono space-y-1">
              <div className="text-[9px] text-[var(--accent-cyan)] uppercase tracking-wider opacity-70">Petronus AI</div>
              <div className="flex items-center gap-2 text-[var(--accent-cyan)]">
                <div className="w-1.5 h-1.5 rounded-full bg-[var(--accent-cyan)] animate-ping" />
                Rebuilding 3D model…
              </div>
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="flex-shrink-0 p-3 border-t border-[var(--border)]">
        {!selectedSite && (
          <div className="text-[10px] font-mono text-[var(--accent-amber)] mb-2 text-center">
            Select a site on the map first
          </div>
        )}
        <div className="flex gap-2">
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
            placeholder={busy ? 'Working…' : 'Tell me what to change or ask anything…'}
            disabled={busy}
            className="flex-1 bg-[var(--surface-3)] border border-[var(--border)] rounded-lg px-3 py-2 text-xs font-mono text-[var(--text-primary)] focus:outline-none focus:border-[var(--accent-cyan)] transition-colors disabled:opacity-50"
          />
          <button
            onClick={() => send()}
            disabled={!input.trim() || busy}
            className="px-3 py-2 rounded-lg text-xs font-mono transition-all"
            style={{
              background: input.trim() && !busy ? 'var(--accent-cyan)' : 'var(--surface-3)',
              color: input.trim() && !busy ? '#0a0a0f' : 'var(--text-secondary)',
            }}
          >
            ↑
          </button>
        </div>
      </div>
    </div>
  );
}
