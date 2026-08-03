'use client';
import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import PetronusLogo from '@/components/ui/PetronusLogo';

const PLANS = [
  {
    name: 'Starter',
    price: '0',
    period: 'Free forever',
    desc: 'For individuals exploring the platform.',
    features: ['5 generations / month', '3D viewer', 'Preliminary code preflight report', 'Email support'],
    cta: 'Current plan',
    active: true,
    color: '#8a8278',
  },
  {
    name: 'Pro',
    price: '149',
    period: 'per month',
    desc: 'For active architects and small firms.',
    features: ['Unlimited generations', 'All massing options', 'Coordinated MEP routing', 'BIM export (IFC)', 'Priority support', 'Custom site parameters'],
    cta: 'Upgrade to Pro',
    active: false,
    color: '#c4a882',
    highlight: true,
  },
  {
    name: 'Enterprise',
    price: 'Custom',
    period: 'Contact us',
    desc: 'For development firms and large teams.',
    features: ['Everything in Pro', 'Team seats', 'API access', 'White-label output', 'Dedicated CSM', 'SLA guarantee'],
    cta: 'Talk to sales',
    active: false,
    color: '#8fa898',
  },
];

export default function BillingPage() {
  const router = useRouter();
  const [annual, setAnnual] = useState(false);

  return (
    <div style={{ minHeight: '100vh', background: '#060504', position: 'relative', overflow: 'hidden' }}>
      <div style={{
        position: 'fixed', inset: 0, pointerEvents: 'none',
        backgroundImage: 'linear-gradient(rgba(196,168,130,0.02) 1px, transparent 1px), linear-gradient(90deg, rgba(196,168,130,0.02) 1px, transparent 1px)',
        backgroundSize: '56px 56px',
      }} />

      {/* Nav */}
      <nav style={{
        position: 'sticky', top: 0, zIndex: 100, padding: '14px 40px',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        background: 'rgba(6,5,4,0.7)', backdropFilter: 'blur(20px)',
        borderBottom: '1px solid rgba(196,168,130,0.06)',
      }}>
        <button onClick={() => router.push('/')} style={{
          display: 'flex', alignItems: 'center', gap: 10, background: 'none', border: 'none', cursor: 'pointer',
        }}>
          <PetronusLogo height={18} color="#c4a882" iconOnly={false} />
          <span style={{ fontFamily: 'Space Grotesk,sans-serif', fontWeight: 700, fontSize: 15, color: '#f0ece4' }}>Petronus</span>
        </button>
        <button onClick={() => router.push('/login')} style={{
          background: 'none', border: '1px solid rgba(196,168,130,0.18)', borderRadius: 8,
          padding: '7px 16px', cursor: 'pointer', fontFamily: 'monospace', fontSize: 11, color: '#8a8278',
          transition: 'all .2s',
        }}
          onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color = '#c4a882'; (e.currentTarget as HTMLElement).style.borderColor = 'rgba(196,168,130,0.4)'; }}
          onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color = '#8a8278'; (e.currentTarget as HTMLElement).style.borderColor = 'rgba(196,168,130,0.18)'; }}
        >
          Sign in
        </button>
      </nav>

      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '80px 40px' }}>
        {/* Header */}
        <div style={{ textAlign: 'center', marginBottom: 60 }}>
          <div style={{ fontFamily: 'monospace', fontSize: 10, color: '#c4a882', letterSpacing: '4px', textTransform: 'uppercase', marginBottom: 14, opacity: .6 }}>Pricing</div>
          <h1 style={{ fontFamily: 'Space Grotesk,sans-serif', fontWeight: 700, fontSize: 'clamp(32px,5vw,56px)', color: '#f0ece4', margin: '0 0 16px' }}>Simple, transparent pricing</h1>
          <p style={{ fontFamily: 'DM Sans,sans-serif', fontSize: 16, color: '#5a5550', maxWidth: 440, margin: '0 auto 36px', lineHeight: 1.7 }}>Start free. Scale when you're ready.</p>

          {/* Annual toggle */}
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 12, background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: 40, padding: '6px 18px' }}>
            <span style={{ fontFamily: 'monospace', fontSize: 11, color: annual ? '#4a4540' : '#c4a882' }}>Monthly</span>
            <button onClick={() => setAnnual(a => !a)} style={{
              width: 36, height: 20, borderRadius: 10, border: 'none', cursor: 'pointer',
              background: annual ? 'rgba(196,168,130,0.3)' : 'rgba(255,255,255,0.08)',
              position: 'relative', transition: 'background .2s',
            }}>
              <div style={{
                position: 'absolute', top: 3, left: annual ? 18 : 3, width: 14, height: 14,
                borderRadius: '50%', background: annual ? '#c4a882' : '#5a5550',
                transition: 'left .2s, background .2s',
              }} />
            </button>
            <span style={{ fontFamily: 'monospace', fontSize: 11, color: annual ? '#c4a882' : '#4a4540' }}>
              Annual <span style={{ color: '#8fa898', fontSize: 9 }}>–20%</span>
            </span>
          </div>
        </div>

        {/* Plan cards */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3,1fr)', gap: 20 }}>
          {PLANS.map(plan => (
            <div key={plan.name} style={{
              padding: '32px 28px',
              borderRadius: 18,
              border: plan.highlight ? '1px solid rgba(196,168,130,0.3)' : '1px solid rgba(255,255,255,0.06)',
              background: plan.highlight ? 'rgba(196,168,130,0.04)' : 'rgba(255,255,255,0.02)',
              boxShadow: plan.highlight ? '0 0 60px rgba(196,168,130,0.06)' : 'none',
              position: 'relative',
              transition: 'transform .25s',
            }}
              onMouseEnter={e => (e.currentTarget as HTMLElement).style.transform = 'translateY(-4px)'}
              onMouseLeave={e => (e.currentTarget as HTMLElement).style.transform = 'none'}
            >
              {plan.highlight && (
                <div style={{
                  position: 'absolute', top: -1, left: '50%', transform: 'translateX(-50%)',
                  fontFamily: 'monospace', fontSize: 9, color: '#060504', background: '#c4a882',
                  padding: '3px 14px', borderRadius: '0 0 8px 8px', letterSpacing: '2px',
                }}>
                  MOST POPULAR
                </div>
              )}
              <div style={{ fontFamily: 'monospace', fontSize: 10, color: plan.color, letterSpacing: '3px', textTransform: 'uppercase', marginBottom: 16, opacity: .8 }}>{plan.name}</div>
              <div style={{ marginBottom: 8 }}>
                <span style={{ fontFamily: 'Space Grotesk,sans-serif', fontWeight: 700, fontSize: plan.price === 'Custom' ? 32 : 40, color: '#f0ece4' }}>
                  {plan.price === 'Custom' ? 'Custom' : (annual && plan.price !== '0') ? `$${Math.round(parseInt(plan.price) * 0.8)}` : plan.price === '0' ? 'Free' : `$${plan.price}`}
                </span>
                {plan.price !== 'Custom' && plan.price !== '0' && (
                  <span style={{ fontFamily: 'monospace', fontSize: 11, color: '#4a4540', marginLeft: 6 }}>/ {annual ? 'mo, billed annually' : 'month'}</span>
                )}
              </div>
              <p style={{ fontFamily: 'DM Sans,sans-serif', fontSize: 13, color: '#5a5550', lineHeight: 1.6, margin: '0 0 24px' }}>{plan.desc}</p>

              <div style={{ marginBottom: 28 }}>
                {plan.features.map(f => (
                  <div key={f} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                    <div style={{ width: 14, height: 14, borderRadius: '50%', border: `1px solid ${plan.color}40`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                      <div style={{ width: 4, height: 4, background: plan.color, borderRadius: '50%' }} />
                    </div>
                    <span style={{ fontFamily: 'DM Sans,sans-serif', fontSize: 13, color: '#8a8278' }}>{f}</span>
                  </div>
                ))}
              </div>

              <button style={{
                width: '100%', padding: '11px 0', borderRadius: 9,
                border: `1px solid ${plan.active ? 'rgba(255,255,255,0.08)' : `rgba(${plan.color === '#c4a882' ? '196,168,130' : plan.color === '#8fa898' ? '143,168,152' : '138,130,120'},0.35)`}`,
                background: plan.active ? 'transparent' : plan.highlight ? 'rgba(196,168,130,0.12)' : 'rgba(255,255,255,0.03)',
                color: plan.active ? '#3a3530' : plan.color,
                fontFamily: 'monospace', fontSize: 11, fontWeight: 600, letterSpacing: '.5px',
                cursor: plan.active ? 'default' : 'pointer', transition: 'all .2s',
              }}>
                {plan.cta}
              </button>
            </div>
          ))}
        </div>

        {/* FAQ / footer note */}
        <div style={{ textAlign: 'center', marginTop: 60 }}>
          <p style={{ fontFamily: 'DM Sans,sans-serif', fontSize: 14, color: '#3a3530', lineHeight: 1.7 }}>
            All plans include California-specific data, parcel analysis, and 3D model viewer.<br />
            Billing and payments coming soon — currently in closed beta.
          </p>
        </div>
      </div>
    </div>
  );
}
