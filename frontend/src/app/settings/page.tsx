'use client';
import React, { useState } from 'react';
import { useRouter } from 'next/navigation';

const PROFILE = {
  name: 'Alex Chen', email: 'alex.chen@badg.io',
  company: 'Bay Area Development Group', role: 'Principal Architect',
  location: 'San Francisco, CA', phone: '+1 (415) 555-0182',
};

function Card({ children, style, id }: { children: React.ReactNode; style?: React.CSSProperties; id?: string }) {
  return (
    <div id={id} style={{ background: '#0d1117', border: '1px solid rgba(255,255,255,0.07)', borderRadius: 16, ...style }}>
      {children}
    </div>
  );
}
function Section({ title, accent, children }: { title: string; accent?: string; children: React.ReactNode }) {
  return (
    <div style={{ padding: '24px 28px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
      <div style={{ fontFamily: 'monospace', fontSize: 10, letterSpacing: '3px',
        textTransform: 'uppercase', color: accent || '#00e5ff', opacity: .7, marginBottom: 20 }}>
        {title}
      </div>
      {children}
    </div>
  );
}
function Field({ label, value, type = 'text', onChange }: {
  label: string; value: string; type?: string; onChange: (v: string) => void;
}) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label style={{ display: 'block', fontFamily: 'monospace', fontSize: 10, color: '#4a4a66',
        letterSpacing: '1px', textTransform: 'uppercase', marginBottom: 7 }}>{label}</label>
      <input type={type} value={value} onChange={e => onChange(e.target.value)} style={{
        width: '100%', padding: '10px 14px', borderRadius: 8, boxSizing: 'border-box',
        background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)',
        color: '#c0c0d8', fontFamily: 'DM Sans,sans-serif', fontSize: 14, outline: 'none',
        transition: 'border-color .2s',
      }}
        onFocus={e => (e.target.style.borderColor = 'rgba(0,229,255,0.4)')}
        onBlur={e => (e.target.style.borderColor = 'rgba(255,255,255,0.08)')}
      />
    </div>
  );
}
function SelectField({ label, value, options, onChange }: {
  label: string; value: string; options: { val: string; label: string }[]; onChange: (v: string) => void;
}) {
  return (
    <div style={{ marginBottom: 16 }}>
      <label style={{ display: 'block', fontFamily: 'monospace', fontSize: 10, color: '#4a4a66',
        letterSpacing: '1px', textTransform: 'uppercase', marginBottom: 7 }}>{label}</label>
      <select value={value} onChange={e => onChange(e.target.value)} style={{
        width: '100%', padding: '10px 14px', borderRadius: 8, boxSizing: 'border-box' as const,
        background: '#0d1117', border: '1px solid rgba(255,255,255,0.08)',
        color: '#c0c0d8', fontFamily: 'DM Sans,sans-serif', fontSize: 14, outline: 'none',
        cursor: 'pointer',
      }}>
        {options.map(o => <option key={o.val} value={o.val} style={{ background: '#0d1117' }}>{o.label}</option>)}
      </select>
    </div>
  );
}
function Toggle({ label, sub, value, onChange }: {
  label: string; sub?: string; value: boolean; onChange: (v: boolean) => void;
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '12px 0', borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
      <div>
        <div style={{ fontFamily: 'DM Sans,sans-serif', fontSize: 14, color: '#c0c0d8' }}>{label}</div>
        {sub && <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#4a4a66', marginTop: 2 }}>{sub}</div>}
      </div>
      <button onClick={() => onChange(!value)} style={{
        width: 44, height: 24, borderRadius: 12, border: 'none', cursor: 'pointer',
        background: value ? 'linear-gradient(90deg,#00e5ff,#00ff88)' : 'rgba(255,255,255,0.1)',
        position: 'relative', transition: 'background .25s', flexShrink: 0,
      }}>
        <div style={{
          position: 'absolute', top: 3, left: value ? 23 : 3,
          width: 18, height: 18, borderRadius: '50%', background: '#fff',
          transition: 'left .25s', boxShadow: '0 1px 4px rgba(0,0,0,0.4)',
        }} />
      </button>
    </div>
  );
}

export default function SettingsPage() {
  const router = useRouter();
  const [profile, setProfile] = useState(PROFILE);
  const [defaults, setDefaults] = useState({
    region: 'CA', structural: 'wood', stories: '2', hvac: 'mini_split', priority: 'cost',
  });
  const [notifs, setNotifs] = useState({
    generation_complete: true, compliance_warnings: true,
    weekly_summary: false, product_updates: true,
  });
  const [appearance, setAppearance] = useState({
    theme: 'dark', grid_visible: true, shadows: true, fog: true,
  });
  const [saved, setSaved] = useState(false);

  const save = () => { setSaved(true); setTimeout(() => setSaved(false), 2000); };

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
            Settings
          </span>
        </div>
        <button onClick={save} style={{
          padding: '8px 20px', borderRadius: 8, fontFamily: 'monospace', fontSize: 12, fontWeight: 600,
          background: saved
            ? 'linear-gradient(135deg,rgba(0,255,136,0.2),rgba(0,255,136,0.12))'
            : 'linear-gradient(135deg,rgba(0,229,255,0.15),rgba(0,255,136,0.1))',
          border: `1px solid ${saved ? 'rgba(0,255,136,0.4)' : 'rgba(0,229,255,0.3)'}`,
          color: saved ? '#00ff88' : '#00e5ff', cursor: 'pointer', transition: 'all .3s',
        }}>
          {saved ? '✓ Saved' : 'Save Changes'}
        </button>
      </nav>

      <div style={{ maxWidth: 860, margin: '0 auto', padding: '36px 36px 80px' }}>
        <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr', gap: 8, alignItems: 'start' }}>

          {/* Sidebar nav */}
          <div style={{ position: 'sticky', top: 80 }}>
            {[
              { id: 'profile',  icon: '◎', label: 'Profile' },
              { id: 'defaults', icon: '◈', label: 'Project Defaults' },
              { id: 'notifs',   icon: '◷', label: 'Notifications' },
              { id: 'viewer',   icon: '◉', label: '3D Viewer' },
              { id: 'account',  icon: '◫', label: 'Account' },
            ].map(item => (
              <a key={item.id} href={`#${item.id}`} style={{
                display: 'flex', alignItems: 'center', gap: 10, padding: '9px 14px',
                borderRadius: 8, textDecoration: 'none', marginBottom: 2,
                fontFamily: 'monospace', fontSize: 12, color: '#4a4a66',
                transition: 'all .15s',
              }}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(0,229,255,0.06)'; (e.currentTarget as HTMLElement).style.color = '#00e5ff'; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = ''; (e.currentTarget as HTMLElement).style.color = '#4a4a66'; }}
              >
                <span style={{ opacity: .6 }}>{item.icon}</span> {item.label}
              </a>
            ))}
          </div>

          {/* Settings panels */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

            {/* Profile */}
            <Card id="profile">
              <Section title="Profile">
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 20px' }}>
                  <Field label="Full name" value={profile.name} onChange={v => setProfile(p => ({ ...p, name: v }))} />
                  <Field label="Email" type="email" value={profile.email} onChange={v => setProfile(p => ({ ...p, email: v }))} />
                  <Field label="Company" value={profile.company} onChange={v => setProfile(p => ({ ...p, company: v }))} />
                  <Field label="Role" value={profile.role} onChange={v => setProfile(p => ({ ...p, role: v }))} />
                  <Field label="Location" value={profile.location} onChange={v => setProfile(p => ({ ...p, location: v }))} />
                  <Field label="Phone" type="tel" value={profile.phone} onChange={v => setProfile(p => ({ ...p, phone: v }))} />
                </div>
              </Section>
            </Card>

            {/* Project defaults */}
            <Card id="defaults">
              <Section title="Project Defaults" accent="#00ff88">
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 20px' }}>
                  <SelectField label="Default Region" value={defaults.region}
                    options={[{ val: 'CA', label: 'California (CA)' }, { val: 'NV', label: 'Nevada (NV)' }]}
                    onChange={v => setDefaults(d => ({ ...d, region: v }))} />
                  <SelectField label="Structural System" value={defaults.structural}
                    options={[{ val: 'wood', label: 'Wood Frame' }, { val: 'steel', label: 'Steel' }, { val: 'concrete', label: 'Concrete' }]}
                    onChange={v => setDefaults(d => ({ ...d, structural: v }))} />
                  <SelectField label="Default Stories" value={defaults.stories}
                    options={[{ val: '1', label: '1 Story' }, { val: '2', label: '2 Stories' }, { val: '3', label: '3 Stories' }]}
                    onChange={v => setDefaults(d => ({ ...d, stories: v }))} />
                  <SelectField label="HVAC Preference" value={defaults.hvac}
                    options={[{ val: 'mini_split', label: 'Mini Split' }, { val: 'rooftop', label: 'Rooftop Package' }]}
                    onChange={v => setDefaults(d => ({ ...d, hvac: v }))} />
                  <SelectField label="Design Priority" value={defaults.priority}
                    options={[{ val: 'cost', label: 'Cost' }, { val: 'speed', label: 'Speed' }, { val: 'daylight', label: 'Daylight' }]}
                    onChange={v => setDefaults(d => ({ ...d, priority: v }))} />
                </div>
              </Section>
            </Card>

            {/* Notifications */}
            <Card id="notifs">
              <Section title="Notifications" accent="#7c3aed">
                <Toggle label="Generation complete" sub="Notify when a model finishes generating"
                  value={notifs.generation_complete} onChange={v => setNotifs(n => ({ ...n, generation_complete: v }))} />
                <Toggle label="Preflight findings" sub="Alert on preliminary code or flood-zone findings"
                  value={notifs.compliance_warnings} onChange={v => setNotifs(n => ({ ...n, compliance_warnings: v }))} />
                <Toggle label="Weekly summary" sub="Projects generated, checks run, avg time"
                  value={notifs.weekly_summary} onChange={v => setNotifs(n => ({ ...n, weekly_summary: v }))} />
                <Toggle label="Product updates" sub="New features and improvements"
                  value={notifs.product_updates} onChange={v => setNotifs(n => ({ ...n, product_updates: v }))} />
              </Section>
            </Card>

            {/* 3D Viewer */}
            <Card id="viewer">
              <Section title="3D Viewer" accent="#ffb300">
                <Toggle label="Show grid" sub="Ground plane grid in the 3D viewer"
                  value={appearance.grid_visible} onChange={v => setAppearance(a => ({ ...a, grid_visible: v }))} />
                <Toggle label="Cast shadows" sub="Directional shadow casting (GPU intensive)"
                  value={appearance.shadows} onChange={v => setAppearance(a => ({ ...a, shadows: v }))} />
                <Toggle label="Distance fog" sub="Fade geometry at far distances"
                  value={appearance.fog} onChange={v => setAppearance(a => ({ ...a, fog: v }))} />
              </Section>
            </Card>

            {/* Account */}
            <Card id="account">
              <Section title="Account" accent="#ff4444">
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '14px 16px', borderRadius: 10, background: 'rgba(255,255,255,0.02)',
                    border: '1px solid rgba(255,255,255,0.05)' }}>
                    <div>
                      <div style={{ fontFamily: 'DM Sans,sans-serif', fontSize: 14, color: '#c0c0d8' }}>Current Plan</div>
                      <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#4a4a66', marginTop: 2 }}>Pro Beta — all features included</div>
                    </div>
                    <span style={{ fontFamily: 'monospace', fontSize: 9, color: '#00e5ff',
                      background: 'rgba(0,229,255,0.1)', border: '1px solid rgba(0,229,255,0.25)',
                      borderRadius: 6, padding: '3px 8px', letterSpacing: '2px' }}>PRO BETA</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '14px 16px', borderRadius: 10, background: 'rgba(255,255,255,0.02)',
                    border: '1px solid rgba(255,255,255,0.05)' }}>
                    <div>
                      <div style={{ fontFamily: 'DM Sans,sans-serif', fontSize: 14, color: '#c0c0d8' }}>Export data</div>
                      <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#4a4a66', marginTop: 2 }}>Download all your project data as JSON</div>
                    </div>
                    <button style={{ padding: '7px 16px', borderRadius: 7, fontFamily: 'monospace', fontSize: 11,
                      background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.1)',
                      color: '#8888aa', cursor: 'pointer' }}>Export</button>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    padding: '14px 16px', borderRadius: 10, background: 'rgba(255,68,68,0.03)',
                    border: '1px solid rgba(255,68,68,0.12)' }}>
                    <div>
                      <div style={{ fontFamily: 'DM Sans,sans-serif', fontSize: 14, color: '#c0c0d8' }}>Delete account</div>
                      <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#4a4a66', marginTop: 2 }}>Permanently remove all data</div>
                    </div>
                    <button style={{ padding: '7px 16px', borderRadius: 7, fontFamily: 'monospace', fontSize: 11,
                      background: 'rgba(255,68,68,0.08)', border: '1px solid rgba(255,68,68,0.25)',
                      color: '#ff4444', cursor: 'pointer' }}>Delete</button>
                  </div>
                </div>
              </Section>
            </Card>

          </div>
        </div>
      </div>
    </div>
  );
}
