'use client';
import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import PetronusLogo from '@/components/ui/PetronusLogo';

export default function LoginPage() {
  const router = useRouter();
  const [tab, setTab] = useState<'signin' | 'signup'>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');

  return (
    <div style={{
      minHeight: '100vh', background: '#060504',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      position: 'relative', overflow: 'hidden',
    }}>
      {/* Fine grid background */}
      <div style={{
        position: 'absolute', inset: 0, pointerEvents: 'none',
        backgroundImage: 'linear-gradient(rgba(196,168,130,0.025) 1px, transparent 1px), linear-gradient(90deg, rgba(196,168,130,0.025) 1px, transparent 1px)',
        backgroundSize: '56px 56px',
      }} />
      {/* Radial glow */}
      <div style={{
        position: 'absolute', inset: 0, pointerEvents: 'none',
        background: 'radial-gradient(ellipse 60% 60% at 50% 50%, rgba(196,168,130,0.04) 0%, transparent 65%)',
      }} />

      {/* Back link */}
      <button onClick={() => router.push('/')} style={{
        position: 'absolute', top: 28, left: 32,
        background: 'none', border: 'none', cursor: 'pointer',
        fontFamily: 'monospace', fontSize: 12, color: '#5a5550',
        display: 'flex', alignItems: 'center', gap: 8, transition: 'color .2s',
      }}
        onMouseEnter={e => (e.currentTarget as HTMLElement).style.color = '#c4a882'}
        onMouseLeave={e => (e.currentTarget as HTMLElement).style.color = '#5a5550'}
      >
        ← Back
      </button>

      <div style={{ position: 'relative', zIndex: 1, width: '100%', maxWidth: 420, padding: '0 24px' }}>
        {/* Logo */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', marginBottom: 40 }}>
          <div style={{ marginBottom: 14 }}>
            <PetronusLogo height={42} color="#c4a882" animated iconOnly />
          </div>
          <span style={{ fontFamily: 'Space Grotesk,sans-serif', fontWeight: 700, fontSize: 20, color: '#f0ece4' }}>Petronus</span>
          <span style={{ fontFamily: 'monospace', fontSize: 10, color: '#4a4540', letterSpacing: '3px', textTransform: 'uppercase', marginTop: 6 }}>Automated BIM Platform</span>
        </div>

        {/* Card */}
        <div style={{
          background: 'rgba(255,255,255,0.025)', borderRadius: 18,
          border: '1px solid rgba(196,168,130,0.12)',
          padding: '36px 36px 40px',
          boxShadow: '0 0 80px rgba(0,0,0,0.4)',
        }}>
          {/* Tab toggle */}
          <div style={{
            display: 'flex', background: 'rgba(255,255,255,0.03)', borderRadius: 10,
            border: '1px solid rgba(255,255,255,0.05)', padding: 3, marginBottom: 32,
          }}>
            {(['signin', 'signup'] as const).map(t => (
              <button key={t} onClick={() => setTab(t)} style={{
                flex: 1, padding: '8px 0', borderRadius: 8, cursor: 'pointer',
                fontFamily: 'monospace', fontSize: 12, letterSpacing: '1px',
                background: tab === t ? 'rgba(196,168,130,0.12)' : 'transparent',
                color: tab === t ? '#c4a882' : '#5a5550',
                border: tab === t ? '1px solid rgba(196,168,130,0.2)' : '1px solid transparent',
                transition: 'all .2s',
              }}>
                {t === 'signin' ? 'Sign in' : 'Sign up'}
              </button>
            ))}
          </div>

          {tab === 'signup' && (
            <div style={{ marginBottom: 18 }}>
              <label style={{ fontFamily: 'monospace', fontSize: 10, color: '#5a5550', letterSpacing: '2px', textTransform: 'uppercase', display: 'block', marginBottom: 8 }}>Full name</label>
              <input value={name} onChange={e => setName(e.target.value)} placeholder="Jane Smith"
                style={inputStyle} />
            </div>
          )}

          <div style={{ marginBottom: 18 }}>
            <label style={{ fontFamily: 'monospace', fontSize: 10, color: '#5a5550', letterSpacing: '2px', textTransform: 'uppercase', display: 'block', marginBottom: 8 }}>Email</label>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com"
              style={inputStyle} />
          </div>

          <div style={{ marginBottom: 28 }}>
            <label style={{ fontFamily: 'monospace', fontSize: 10, color: '#5a5550', letterSpacing: '2px', textTransform: 'uppercase', display: 'block', marginBottom: 8 }}>Password</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••"
              style={inputStyle} />
          </div>

          <button style={{
            width: '100%', padding: '13px 0', borderRadius: 10, border: '1px solid rgba(196,168,130,0.35)',
            background: 'rgba(196,168,130,0.1)', color: '#c4a882',
            fontFamily: 'monospace', fontSize: 12, fontWeight: 600, letterSpacing: '.5px',
            cursor: 'pointer', transition: 'all .2s',
          }}
            onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(196,168,130,0.18)'; (e.currentTarget as HTMLElement).style.borderColor = 'rgba(196,168,130,0.6)'; }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(196,168,130,0.1)'; (e.currentTarget as HTMLElement).style.borderColor = 'rgba(196,168,130,0.35)'; }}
          >
            {tab === 'signin' ? 'Sign in →' : 'Create account →'}
          </button>

          {tab === 'signin' && (
            <div style={{ textAlign: 'center', marginTop: 20 }}>
              <button style={{ background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'monospace', fontSize: 11, color: '#4a4540', transition: 'color .2s' }}
                onMouseEnter={e => (e.currentTarget as HTMLElement).style.color = '#c4a882'}
                onMouseLeave={e => (e.currentTarget as HTMLElement).style.color = '#4a4540'}
              >
                Forgot password?
              </button>
            </div>
          )}

          <div style={{ marginTop: 28, paddingTop: 24, borderTop: '1px solid rgba(255,255,255,0.05)' }}>
            <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#3a3530', textAlign: 'center', letterSpacing: '1px', marginBottom: 14 }}>Or continue with</div>
            <div style={{ display: 'flex', gap: 10 }}>
              {['Google', 'GitHub'].map(provider => (
                <button key={provider} style={{
                  flex: 1, padding: '10px 0', borderRadius: 9, border: '1px solid rgba(255,255,255,0.07)',
                  background: 'rgba(255,255,255,0.025)', color: '#6a6560',
                  fontFamily: 'monospace', fontSize: 11, cursor: 'pointer', transition: 'all .2s',
                }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(196,168,130,0.05)'; (e.currentTarget as HTMLElement).style.borderColor = 'rgba(196,168,130,0.18)'; (e.currentTarget as HTMLElement).style.color = '#c4a882'; }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.025)'; (e.currentTarget as HTMLElement).style.borderColor = 'rgba(255,255,255,0.07)'; (e.currentTarget as HTMLElement).style.color = '#6a6560'; }}
                >
                  {provider}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div style={{ textAlign: 'center', marginTop: 24, fontFamily: 'monospace', fontSize: 9, color: '#2a2520', letterSpacing: '1.5px' }}>
          BETA · CALIFORNIA MULTI-FAMILY RESIDENTIAL
        </div>
      </div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: '100%', padding: '11px 14px', borderRadius: 9,
  background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)',
  color: '#f0ece4', fontFamily: 'DM Sans,sans-serif', fontSize: 14,
  outline: 'none', transition: 'border-color .2s', boxSizing: 'border-box',
};
