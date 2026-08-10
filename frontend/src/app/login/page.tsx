'use client';
import React, { useState, useEffect, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import PetronusLogo from '@/components/ui/PetronusLogo';
import { useAppStore } from '@/lib/store';

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// Suspense wrapper required by Next.js 14 for useSearchParams
export default function LoginPage() {
  return (
    <Suspense fallback={<div style={{ minHeight: '100vh', background: '#060504' }} />}>
      <LoginContent />
    </Suspense>
  );
}

function LoginContent() {
  const router = useRouter();
  const params = useSearchParams();
  const { setAuth, user, token: storedToken } = useAppStore();

  const [tab, setTab] = useState<'signin' | 'signup'>('signin');
  // Dev mode: pre-fill with demo credentials so the form looks realistic
  const [email, setEmail] = useState(process.env.NODE_ENV === 'development' ? 'demo@petronus.app' : '');
  const [password, setPassword] = useState(process.env.NODE_ENV === 'development' ? 'demo1234' : '');
  const [name, setName] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // If already authed, go to app
  useEffect(() => {
    if (user && storedToken) router.replace('/');
  }, [user, storedToken, router]);

  // Handle Google OAuth redirect token
  useEffect(() => {
    const t = params.get('token');
    const err = params.get('error');
    if (t) {
      fetchMeWithToken(t);
    } else if (err) {
      setError(err === 'google_denied' ? 'Google sign-in was cancelled.' : 'Google sign-in failed. Try again.');
    }
  }, [params]);

  async function fetchMeWithToken(t: string) {
    try {
      const res = await fetch(`${API}/api/auth/me`, { headers: { Authorization: `Bearer ${t}` } });
      if (res.ok) {
        const me = await res.json();
        setAuth(me, t);
        router.replace('/');
      }
    } catch {}
  }

  async function handleSubmit() {
    setError('');
    if (!email || !password) { setError('Please fill in all fields.'); return; }
    if (tab === 'signup' && !name) { setError('Please enter your name.'); return; }
    setLoading(true);
    try {
      const endpoint = tab === 'signin' ? '/api/auth/login' : '/api/auth/register';
      const body: any = tab === 'signin' ? { email, password } : { name, email, password };
      const res = await fetch(`${API}${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        setError(data.detail || 'Something went wrong.');
      } else {
        setAuth(data.user, data.token);
        router.replace('/');
      }
    } catch {
      setError('Could not connect to server. Is the backend running?');
    } finally {
      setLoading(false);
    }
  }

  function handleSkip() {
    // Dev bypass — sets a realistic-looking demo user so the full UI is visible
    setAuth({ id: 'demo', name: 'Alex Chen', email: 'demo@petronus.app', avatar: '' }, '__dev_skip__');
    router.replace('/');
  }

  function handleGoogle() {
    window.location.href = `${API}/api/auth/google`;
  }

  const isDev = process.env.NODE_ENV === 'development';

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

      {/* Dev skip button — top right */}
      {isDev && (
        <button onClick={handleSkip} style={{
          position: 'absolute', top: 28, right: 32,
          background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)',
          borderRadius: 7, padding: '6px 14px', cursor: 'pointer',
          fontFamily: 'monospace', fontSize: 10, color: '#4a4540',
          letterSpacing: '1px', transition: 'all .2s',
        }}
          onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = '#c4a882'; (e.currentTarget as HTMLElement).style.borderColor = 'rgba(196,168,130,0.25)'; }}
          onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = '#4a4540'; (e.currentTarget as HTMLElement).style.borderColor = 'rgba(255,255,255,0.08)'; }}
        >
          Skip (Dev)
        </button>
      )}

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
              <button key={t} onClick={() => { setTab(t); setError(''); }} style={{
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
              <label style={labelStyle}>Full name</label>
              <input value={name} onChange={e => setName(e.target.value)} placeholder="Jane Smith"
                onKeyDown={e => e.key === 'Enter' && handleSubmit()}
                style={inputStyle} />
            </div>
          )}

          <div style={{ marginBottom: 18 }}>
            <label style={labelStyle}>Email</label>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@example.com"
              onKeyDown={e => e.key === 'Enter' && handleSubmit()}
              style={inputStyle} />
          </div>

          <div style={{ marginBottom: error ? 16 : 28 }}>
            <label style={labelStyle}>Password</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••"
              onKeyDown={e => e.key === 'Enter' && handleSubmit()}
              style={inputStyle} />
          </div>

          {/* Error message */}
          {error && (
            <div style={{
              marginBottom: 16, padding: '10px 14px', borderRadius: 8,
              background: 'rgba(220,60,60,0.08)', border: '1px solid rgba(220,60,60,0.2)',
              fontFamily: 'monospace', fontSize: 11, color: '#e07070', letterSpacing: '0.5px',
            }}>
              {error}
            </div>
          )}

          <button
            onClick={handleSubmit}
            disabled={loading}
            style={{
              width: '100%', padding: '13px 0', borderRadius: 10, border: '1px solid rgba(196,168,130,0.35)',
              background: loading ? 'rgba(196,168,130,0.05)' : 'rgba(196,168,130,0.1)',
              color: loading ? '#6a6055' : '#c4a882',
              fontFamily: 'monospace', fontSize: 12, fontWeight: 600, letterSpacing: '.5px',
              cursor: loading ? 'not-allowed' : 'pointer', transition: 'all .2s',
            }}
            onMouseEnter={e => { if (!loading) { (e.currentTarget as HTMLElement).style.background = 'rgba(196,168,130,0.18)'; (e.currentTarget as HTMLElement).style.borderColor = 'rgba(196,168,130,0.6)'; } }}
            onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = loading ? 'rgba(196,168,130,0.05)' : 'rgba(196,168,130,0.1)'; (e.currentTarget as HTMLElement).style.borderColor = 'rgba(196,168,130,0.35)'; }}
          >
            {loading ? 'Please wait…' : tab === 'signin' ? 'Sign in →' : 'Create account →'}
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
              <button onClick={handleGoogle} style={oauthBtn}
                onMouseEnter={e => oauthHover(e, true)}
                onMouseLeave={e => oauthHover(e, false)}
              >
                Google
              </button>
              <button
                title="GitHub OAuth coming soon"
                style={{ ...oauthBtn, cursor: 'not-allowed', opacity: 0.4 }}
              >
                GitHub
              </button>
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

const labelStyle: React.CSSProperties = {
  fontFamily: 'monospace', fontSize: 10, color: '#5a5550',
  letterSpacing: '2px', textTransform: 'uppercase', display: 'block', marginBottom: 8,
};

const inputStyle: React.CSSProperties = {
  width: '100%', padding: '11px 14px', borderRadius: 9,
  background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)',
  color: '#f0ece4', fontFamily: 'DM Sans,sans-serif', fontSize: 14,
  outline: 'none', transition: 'border-color .2s', boxSizing: 'border-box',
};

const oauthBtn: React.CSSProperties = {
  flex: 1, padding: '10px 0', borderRadius: 9, border: '1px solid rgba(255,255,255,0.07)',
  background: 'rgba(255,255,255,0.025)', color: '#6a6560',
  fontFamily: 'monospace', fontSize: 11, cursor: 'pointer', transition: 'all .2s',
};

function oauthHover(e: React.MouseEvent<HTMLButtonElement>, enter: boolean) {
  const el = e.currentTarget as HTMLElement;
  el.style.background    = enter ? 'rgba(196,168,130,0.05)' : 'rgba(255,255,255,0.025)';
  el.style.borderColor   = enter ? 'rgba(196,168,130,0.18)' : 'rgba(255,255,255,0.07)';
  el.style.color         = enter ? '#c4a882' : '#6a6560';
}
