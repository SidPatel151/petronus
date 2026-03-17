'use client';
import React, { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';

// ─── Particle canvas (background, all sections) ────────────────────────────
function ParticleCanvas() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current; if (!canvas) return;
    const ctx = canvas.getContext('2d'); if (!ctx) return;
    let raf: number;
    type P = { x:number; y:number; vx:number; vy:number; size:number; alpha:number; color:string };
    const COLS = ['#00e5ff','#00ff88','#7c3aed','#ffffff'];
    const ps: P[] = [];
    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = Math.max(document.documentElement.scrollHeight, window.innerHeight);
    };
    resize();
    // Re-measure after fonts/images load
    window.addEventListener('resize', resize);
    window.addEventListener('load', resize);
    for (let i = 0; i < 350; i++) ps.push({
      x: Math.random()*canvas.width, y: Math.random()*canvas.height,
      vx:(Math.random()-.5)*.35, vy:(Math.random()-.5)*.35,
      size:Math.random()*1.8+.3, alpha:Math.random()*.45+.1,
      color:COLS[Math.floor(Math.random()*COLS.length)],
    });
    function draw() {
      ctx!.clearRect(0,0,canvas!.width,canvas!.height);
      for (let i=0;i<ps.length;i++) for (let j=i+1;j<ps.length;j++) {
        const dx=ps[i].x-ps[j].x,dy=ps[i].y-ps[j].y,d=Math.sqrt(dx*dx+dy*dy);
        if(d<100){ctx!.beginPath();ctx!.strokeStyle=`rgba(0,229,255,${.06*(1-d/100)})`;ctx!.lineWidth=.4;ctx!.moveTo(ps[i].x,ps[i].y);ctx!.lineTo(ps[j].x,ps[j].y);ctx!.stroke();}
      }
      for(const p of ps){
        p.x+=p.vx;p.y+=p.vy;
        if(p.x<0)p.x=canvas!.width;else if(p.x>canvas!.width)p.x=0;
        if(p.y<0)p.y=canvas!.height;else if(p.y>canvas!.height)p.y=0;
        ctx!.beginPath();ctx!.arc(p.x,p.y,p.size,0,Math.PI*2);
        ctx!.fillStyle=p.color;ctx!.globalAlpha=p.alpha;ctx!.fill();ctx!.globalAlpha=1;
      }
      raf=requestAnimationFrame(draw);
    }
    draw();
    return ()=>{cancelAnimationFrame(raf);window.removeEventListener('resize',resize);window.removeEventListener('load',resize);};
  },[]);
  return <canvas ref={ref} style={{position:'fixed',inset:0,pointerEvents:'none',zIndex:0,opacity:.6}} />;
}

// ─── 3D building wireframe canvas ──────────────────────────────────────────
function BuildingWireframe() {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(()=>{
    const canvas=ref.current; if(!canvas) return;
    const ctx=canvas.getContext('2d'); if(!ctx) return;
    canvas.width=460; canvas.height=460;
    let raf:number, rotY=0.3;
    const W=2.6,D=3.4,FLOORS=4,FH=1.15;
    // vertices: 4 corners × (FLOORS+1) levels
    const verts:number[][]=[];
    for(let f=0;f<=FLOORS;f++){
      const y=f*FH;
      verts.push([-W/2,y,-D/2],[ W/2,y,-D/2],[ W/2,y, D/2],[-W/2,y, D/2]);
    }
    // floor plate edges + vertical columns
    const edges:number[][]=[];
    for(let f=0;f<=FLOORS;f++){const b=f*4;edges.push([b,b+1],[b+1,b+2],[b+2,b+3],[b+3,b]);}
    for(let c=0;c<4;c++) for(let f=0;f<FLOORS;f++) edges.push([f*4+c,(f+1)*4+c]);
    // interior grid lines (mid-bay columns)
    for(let f=0;f<=FLOORS;f++){const b=f*4;edges.push([b, b+1-1+1]);}
    // window grid lines on front face (z=-D/2)
    for(let f=0;f<FLOORS;f++){
      const y0=f*FH, y1=(f+.5)*FH, y2=(f+.85)*FH;
      // horizontal window sill / header on front
      const vBase=verts.length;
      verts.push([-W/2,y1,-D/2],[W/2,y1,-D/2],[-W/2,y2,-D/2],[W/2,y2,-D/2]);
      edges.push([vBase,vBase+1],[vBase+2,vBase+3]);
      // mullions
      for(let m=1;m<3;m++){const x=-W/2+m*(W/3);const mv=verts.length;verts.push([x,y1,-D/2],[x,y2,-D/2]);edges.push([mv,mv+1]);}
    }
    // total edges to animate drawing
    const totalEdges=edges.length;
    let drawn=0, phase:'draw'|'rotate'='draw';
    const DRAW_SPEED=2;
    function project(vx:number,vy:number,vz:number,ry:number):[number,number]{
      const cos=Math.cos(ry),sin=Math.sin(ry);
      const rx=vx*cos-vz*sin, rz=vx*sin+vz*cos;
      const FOV=260,DIST=7,cx=canvas!.width*.48,cy=canvas!.height*.52;
      const s=FOV/(DIST+rz);
      return [cx+rx*s, cy-vy*s+30];
    }
    function draw(){
      ctx!.clearRect(0,0,canvas!.width,canvas!.height);
      if(phase==='draw'){drawn=Math.min(drawn+DRAW_SPEED,totalEdges);if(drawn>=totalEdges)phase='rotate';}
      else rotY+=.005;
      const edgesToDraw=phase==='draw'?drawn:totalEdges;
      for(let i=0;i<edgesToDraw;i++){
        const [a,b]=edges[i];
        if(a>=verts.length||b>=verts.length) continue;
        const [ax,ay]=project(...(verts[a] as [number,number,number]),rotY);
        const [bx,by]=project(...(verts[b] as [number,number,number]),rotY);
        // deeper lines dimmer
        const vz_a=verts[a][2],vz_b=verts[b][2];
        const avgZ=(vz_a+vz_b)/2/(D*1.2)+.5;
        const alpha=0.25+avgZ*0.65;
        ctx!.beginPath();
        ctx!.strokeStyle=`rgba(0,229,255,${alpha})`;
        ctx!.shadowColor='#00e5ff';
        ctx!.shadowBlur=i<edges.slice(0,FLOORS*4+4*FLOORS).length?6:3;
        ctx!.lineWidth=avgZ>.6?1.2:.7;
        ctx!.moveTo(ax,ay);ctx!.lineTo(bx,by);ctx!.stroke();
      }
      // floor labels
      if(phase==='rotate'){
        for(let f=1;f<=FLOORS;f++){
          const [px,py]=project(-W/2-.15,f*FH-.5,-D/2,rotY);
          ctx!.fillStyle=`rgba(0,229,255,0.35)`;
          ctx!.font='10px JetBrains Mono,monospace';
          ctx!.fillText(`L${f}`,px-18,py+4);
        }
      }
      raf=requestAnimationFrame(draw);
    }
    draw();
    return ()=>cancelAnimationFrame(raf);
  },[]);
  return (
    <canvas ref={ref} style={{width:460,height:460,opacity:.9,filter:'drop-shadow(0 0 30px rgba(0,229,255,0.3))'}} />
  );
}

// ─── Fade-in on scroll ──────────────────────────────────────────────────────
function FadeIn({children,delay=0,className=''}:{children:React.ReactNode;delay?:number;className?:string}){
  const ref=useRef<HTMLDivElement>(null);
  const [vis,setVis]=useState(false);
  useEffect(()=>{
    const el=ref.current; if(!el) return;
    const obs=new IntersectionObserver(([e])=>{if(e.isIntersecting)setVis(true);},{threshold:.15});
    obs.observe(el);
    return ()=>obs.disconnect();
  },[]);
  return (
    <div ref={ref} style={{
      opacity:vis?1:0,
      transform:vis?'translateY(0)':'translateY(28px)',
      transition:`opacity .7s ease ${delay}s, transform .7s ease ${delay}s`,
    }} className={className}>
      {children}
    </div>
  );
}

// ─── Architectural splash screen ────────────────────────────────────────────
function SplashScreen({ onDone }: { onDone: () => void }) {
  const [phase, setPhase] = useState<'grid'|'bracket'|'scan'|'text'|'bar'|'exit'>('grid');
  const [typed, setTyped] = useState('');
  const [scanY, setScanY] = useState(0);
  const [barW, setBarW] = useState(0);
  const [ringsActive, setRingsActive] = useState(false);
  const WORD = 'PETRONUS';

  useEffect(() => {
    const t1 = setTimeout(() => setPhase('bracket'), 400);
    const t2 = setTimeout(() => setPhase('scan'), 900);

    let scanStart: number | null = null;
    let scanRaf: number;
    const animScan = (ts: number) => {
      if (!scanStart) scanStart = ts;
      const p = Math.min((ts - scanStart) / 600, 1);
      setScanY(p * 100);
      if (p < 1) scanRaf = requestAnimationFrame(animScan);
    };
    const t3 = setTimeout(() => { setPhase('scan'); scanRaf = requestAnimationFrame(animScan); }, 900);
    const t3b = setTimeout(() => setRingsActive(true), 1520);

    let ti = 0;
    const typeNext = () => { ti++; setTyped(WORD.slice(0, ti)); if (ti < WORD.length) setTimeout(typeNext, 80); };
    const t4 = setTimeout(() => { setPhase('text'); typeNext(); }, 1560);

    let barStart: number | null = null;
    let barRaf: number;
    const animBar = (ts: number) => {
      if (!barStart) barStart = ts;
      const p = Math.min((ts - barStart) / 900, 1);
      setBarW(p * 100);
      if (p < 1) barRaf = requestAnimationFrame(animBar);
    };
    const t5 = setTimeout(() => { setPhase('bar'); barRaf = requestAnimationFrame(animBar); }, 1900);

    const t6 = setTimeout(() => setPhase('exit'), 2900);
    const t7 = setTimeout(() => onDone(), 3500);

    return () => {
      [t1,t2,t3,t3b,t4,t5,t6,t7].forEach(clearTimeout);
      cancelAnimationFrame(scanRaf);
      cancelAnimationFrame(barRaf);
    };
  }, []);

  const leaving = phase === 'exit';
  const showBrackets = ['bracket','scan','text','bar','exit'].includes(phase);
  const showScan = ['scan','text','bar','exit'].includes(phase);
  const showText = ['text','bar','exit'].includes(phase);
  const showBar = ['bar','exit'].includes(phase);

  const BR = 32; // bracket arm length
  const bracketStyle = (corner: 'tl'|'tr'|'bl'|'br'): React.CSSProperties => {
    const base: React.CSSProperties = {
      position:'absolute', width:BR, height:BR, transition:'opacity .3s',
      opacity: showBrackets ? 1 : 0,
    };
    if (corner==='tl') return { ...base, top:-8,left:-8, borderTop:'2px solid #00e5ff', borderLeft:'2px solid #00e5ff' };
    if (corner==='tr') return { ...base, top:-8,right:-8, borderTop:'2px solid #00e5ff', borderRight:'2px solid #00e5ff' };
    if (corner==='bl') return { ...base, bottom:-8,left:-8, borderBottom:'2px solid #00e5ff', borderLeft:'2px solid #00e5ff' };
    return { ...base, bottom:-8,right:-8, borderBottom:'2px solid #00e5ff', borderRight:'2px solid #00e5ff' };
  };

  return (
    <div style={{
      position:'fixed', inset:0, zIndex:1000,
      background:'#050a0f',
      display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center',
      opacity: leaving ? 0 : 1,
      transition: leaving ? 'opacity .6s ease' : 'none',
    }}>
      {/* Blueprint grid */}
      <div style={{
        position:'absolute', inset:0, pointerEvents:'none',
        backgroundImage: 'linear-gradient(rgba(0,229,255,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(0,229,255,0.04) 1px, transparent 1px)',
        backgroundSize: '40px 40px',
        opacity: leaving ? 0 : 1,
        transition: 'opacity .6s',
      }}/>
      {/* Center crosshairs */}
      <div style={{position:'absolute',top:'50%',left:0,right:0,height:'1px',background:'rgba(0,229,255,0.07)',transform:'translateY(-50%)'}}/>
      <div style={{position:'absolute',left:'50%',top:0,bottom:0,width:'1px',background:'rgba(0,229,255,0.07)',transform:'translateX(-50%)'}}/>

      {/* Expanding rings on scan complete */}
      {ringsActive && [0,1,2].map(i=>(
        <div key={i} style={{
          position:'absolute', top:'50%', left:'50%',
          transform:'translate(-50%,-50%)',
          borderRadius:'50%',
          border:'1px solid rgba(0,229,255,0.5)',
          animation:`splashOrbit ${0.9+i*0.3}s ease-out ${i*0.18}s both`,
          pointerEvents:'none',
          width:160+i*70, height:160+i*70,
        }}/>
      ))}

      {/* Logo container with CAD brackets */}
      <div style={{position:'relative',display:'inline-block',marginBottom:32}}>
        {/* Dimension lines */}
        {showBrackets && (
          <>
            <div style={{position:'absolute',top:'50%',left:-48,transform:'translateY(-50%)',
              width:32,height:'1px',background:'rgba(0,229,255,0.4)',
              transition:'opacity .4s',opacity:showBrackets?1:0}}/>
            <div style={{position:'absolute',top:'50%',right:-48,transform:'translateY(-50%)',
              width:32,height:'1px',background:'rgba(0,229,255,0.4)',
              transition:'opacity .4s',opacity:showBrackets?1:0}}/>
            <div style={{position:'absolute',top:-48,left:'50%',transform:'translateX(-50%)',
              height:32,width:'1px',background:'rgba(0,229,255,0.4)',
              transition:'opacity .4s',opacity:showBrackets?1:0}}/>
            <div style={{position:'absolute',bottom:-48,left:'50%',transform:'translateX(-50%)',
              height:32,width:'1px',background:'rgba(0,229,255,0.4)',
              transition:'opacity .4s',opacity:showBrackets?1:0}}/>
            {/* Tick ends */}
            {[{top:'50%',left:-52,w:6,h:14,mt:'-7px'},{top:'50%',right:-52,w:6,h:14,mt:'-7px'},
              {left:'50%',top:-52,w:14,h:6,ml:'-7px'},{left:'50%',bottom:-52,w:14,h:6,ml:'-7px'}
            ].map((t,i)=>(
              <div key={i} style={{position:'absolute',...(t.mt?{marginTop:t.mt}:{}), ...(t.ml?{marginLeft:t.ml}:{}),
                ...(t.top?{top:t.top}:{}), ...(t.left?{left:t.left}:{}),
                ...(t.right?{right:t.right}:{}), ...(t.bottom?{bottom:t.bottom}:{}),
                width:t.w, height:t.h,
                background:'rgba(0,229,255,0.5)',
              }}/>
            ))}
          </>
        )}
        {/* Corner brackets */}
        <div style={bracketStyle('tl')}/>
        <div style={bracketStyle('tr')}/>
        <div style={bracketStyle('bl')}/>
        <div style={bracketStyle('br')}/>

        {/* Animated logo */}
        <div style={{
          position:'relative', width:120, height:120,
          borderRadius:24, overflow:'hidden',
          boxShadow: showText
            ? '0 0 0 1px rgba(0,229,255,0.3), 0 0 60px rgba(0,229,255,0.4), 0 0 120px rgba(0,229,255,0.15)'
            : '0 0 0 1px rgba(0,229,255,0.1)',
          transition: 'box-shadow .8s ease',
          animation: showText ? 'logoBreath 3.5s ease-in-out infinite' : 'none',
        }}>
          <img src="/petronus.png" alt="Petronus" style={{
            width:'100%', height:'100%', objectFit:'cover', display:'block',
            filter: showText ? 'brightness(1) saturate(1.15)' : 'brightness(0.25)',
            transition: 'filter .6s ease',
            animation: showText ? 'logoFloat 6s ease-in-out infinite' : 'none',
          }}/>
          {/* Scan line */}
          {showScan && scanY < 100 && (
            <div style={{
              position:'absolute', left:0, right:0, top:0,
              height:`${scanY}%`,
              background:'linear-gradient(180deg,rgba(0,229,255,0.06),rgba(0,229,255,0.22))',
              borderBottom:'1.5px solid rgba(0,229,255,0.95)',
              transition:'none',
            }}/>
          )}
          {/* Shimmer sweep — repeats after reveal */}
          {showText && (
            <div style={{
              position:'absolute', inset:0, pointerEvents:'none',
              background:'linear-gradient(115deg, transparent 30%, rgba(255,255,255,0.18) 50%, transparent 70%)',
              animation:'logoShimmer 2.8s ease-in-out infinite',
            }}/>
          )}
          {/* Subtle cyan tint overlay pulsing */}
          {showText && (
            <div style={{
              position:'absolute', inset:0, pointerEvents:'none',
              background:'rgba(0,229,255,0.06)',
              animation:'logoCyanPulse 3s ease-in-out infinite',
            }}/>
          )}
        </div>
      </div>

      {/* Typewriter name */}
      <div style={{
        fontFamily:'Space Grotesk,sans-serif', fontWeight:700, fontSize:36,
        letterSpacing:'0.2em',
        background:'linear-gradient(135deg,#f0f0f8,#00e5ff)',
        WebkitBackgroundClip:'text', WebkitTextFillColor:'transparent', backgroundClip:'text',
        minHeight:44, marginBottom:10,
        opacity: showText ? 1 : 0, transition:'opacity .3s',
      }}>
        {typed}<span style={{opacity: typed.length < WORD.length ? 1 : 0, borderRight:'2px solid #00e5ff'}}>&nbsp;</span>
      </div>

      {/* Subtitle */}
      <div style={{
        fontFamily:'monospace', fontSize:11, color:'#00e5ff',
        letterSpacing:'4px', textTransform:'uppercase', marginBottom:40,
        opacity: showText ? 0.6 : 0, transition:'opacity .5s .3s',
      }}>
        Automated BIM Platform
      </div>

      {/* Architectural progress bar */}
      <div style={{
        width:280, opacity: showBar ? 1 : 0, transition:'opacity .3s',
      }}>
        <div style={{display:'flex',justifyContent:'space-between',marginBottom:6}}>
          <span style={{fontFamily:'monospace',fontSize:9,color:'rgba(0,229,255,0.4)',letterSpacing:'2px'}}>INITIALIZING</span>
          <span style={{fontFamily:'monospace',fontSize:9,color:'rgba(0,229,255,0.4)'}}>{Math.round(barW)}%</span>
        </div>
        <div style={{height:3,background:'rgba(0,229,255,0.1)',borderRadius:2,position:'relative',overflow:'visible'}}>
          <div style={{
            height:'100%', width:`${barW}%`,
            background:'linear-gradient(90deg,#00e5ff,#00ff88)',
            borderRadius:2,
            boxShadow:'0 0 8px rgba(0,229,255,0.6)',
            transition:'none',
          }}/>
          {/* Tick marks */}
          {[25,50,75].map(pct=>(
            <div key={pct} style={{
              position:'absolute', top:-3, left:`${pct}%`,
              width:1, height:9, background:'rgba(0,229,255,0.25)',
              transform:'translateX(-50%)',
            }}/>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Nav drawer ─────────────────────────────────────────────────────────────
const FAKE_PROJECTS = [
  { id:'1', name:'Fremont Infill — 4 Units', addr:'37823 Fremont Blvd, Fremont CA', date:'Mar 12, 2026', stories:3, units:4, status:'generated' },
  { id:'2', name:'Oakland ADU Stack',        addr:'2210 Telegraph Ave, Oakland CA',  date:'Mar 8, 2026',  stories:2, units:2, status:'generated' },
  { id:'3', name:'San Jose Mixed-Use',       addr:'115 S Market St, San Jose CA',    date:'Feb 28, 2026', stories:3, units:6, status:'review' },
];

function NavDrawer({ open, onClose, router }: { open:boolean; onClose:()=>void; router:any }) {
  return (
    <>
      {/* Backdrop */}
      {open && <div onClick={onClose} style={{position:'fixed',inset:0,zIndex:199,background:'rgba(0,0,0,0.5)',backdropFilter:'blur(4px)'}}/>}
      {/* Panel */}
      <div style={{
        position:'fixed', top:0, right:0, bottom:0, zIndex:200,
        width: 340, background:'#0a0d14',
        borderLeft:'1px solid rgba(0,229,255,0.12)',
        transform: open ? 'translateX(0)' : 'translateX(100%)',
        transition:'transform .35s cubic-bezier(0.22,1,0.36,1)',
        display:'flex', flexDirection:'column',
        boxShadow: open ? '-20px 0 60px rgba(0,0,0,0.6)' : 'none',
        overflow:'hidden',
      }}>
        {/* Header */}
        <div style={{padding:'20px 24px',borderBottom:'1px solid rgba(255,255,255,0.06)',
          display:'flex',alignItems:'center',justifyContent:'space-between',flexShrink:0}}>
          <div style={{display:'flex',alignItems:'center',gap:10}}>
            <img src="/petronus.png" alt="" style={{width:28,height:28,borderRadius:8,objectFit:'cover'}}/>
            <span style={{fontFamily:'Space Grotesk,sans-serif',fontWeight:700,fontSize:15,
              background:'linear-gradient(135deg,#00e5ff,#00ff88)',
              WebkitBackgroundClip:'text',WebkitTextFillColor:'transparent',backgroundClip:'text'}}>
              Petronus
            </span>
          </div>
          <button onClick={onClose} style={{background:'none',border:'none',color:'#8888aa',cursor:'pointer',fontSize:20,lineHeight:1,padding:4}}>×</button>
        </div>

        {/* Nav links */}
        <div style={{padding:'16px 12px 8px',borderBottom:'1px solid rgba(255,255,255,0.06)',flexShrink:0}}>
          <button onClick={()=>{router.push('/app');onClose();}} style={{
            width:'100%',padding:'11px 16px',borderRadius:10,display:'flex',alignItems:'center',gap:12,
            background:'linear-gradient(135deg,rgba(0,229,255,0.12),rgba(0,255,136,0.07))',
            border:'1px solid rgba(0,229,255,0.25)',cursor:'pointer',marginBottom:6,
          }}>
            <span style={{fontSize:15}}>⚡</span>
            <span style={{fontFamily:'monospace',fontSize:13,color:'#00e5ff',fontWeight:600}}>Launch App</span>
            <span style={{marginLeft:'auto',fontFamily:'monospace',fontSize:10,color:'#00e5ff',opacity:.5}}>→</span>
          </button>
          {[
            {icon:'◫',label:'Dashboard',sub:'Overview & analytics',href:'/dashboard',live:true},
            {icon:'◈',label:'My Projects',sub:'Saved building models',href:'/projects',live:false},
            {icon:'◎',label:'Settings',sub:'Account & preferences',href:'/settings',live:true},
          ].map(item=>(
            item.live ? (
              <button key={item.label} onClick={()=>{router.push(item.href);onClose();}} style={{
                width:'100%',padding:'11px 16px',borderRadius:10,display:'flex',alignItems:'center',gap:12,
                background:'rgba(255,255,255,0.02)',border:'1px solid rgba(255,255,255,0.06)',
                cursor:'pointer',marginBottom:6,transition:'all .15s',
              }}
                onMouseEnter={e=>{(e.currentTarget as HTMLElement).style.background='rgba(0,229,255,0.06)';(e.currentTarget as HTMLElement).style.borderColor='rgba(0,229,255,0.2)';}}
                onMouseLeave={e=>{(e.currentTarget as HTMLElement).style.background='rgba(255,255,255,0.02)';(e.currentTarget as HTMLElement).style.borderColor='rgba(255,255,255,0.06)';}}
              >
                <span style={{fontSize:15}}>{item.icon}</span>
                <div style={{textAlign:'left'}}>
                  <div style={{fontFamily:'monospace',fontSize:12,color:'#c0c0d8'}}>{item.label}</div>
                  <div style={{fontFamily:'monospace',fontSize:9,color:'#4a4a66',marginTop:1}}>{item.sub}</div>
                </div>
                <span style={{marginLeft:'auto',fontFamily:'monospace',fontSize:10,color:'#4a4a66',opacity:.5}}>→</span>
              </button>
            ) : (
              <div key={item.label} style={{
                width:'100%',padding:'11px 16px',borderRadius:10,display:'flex',alignItems:'center',gap:12,
                background:'rgba(255,255,255,0.02)',border:'1px solid rgba(255,255,255,0.05)',
                cursor:'default',marginBottom:6,opacity:.5,
              }}>
                <span style={{fontSize:15}}>{item.icon}</span>
                <div>
                  <div style={{fontFamily:'monospace',fontSize:12,color:'#c0c0d8'}}>{item.label}</div>
                  <div style={{fontFamily:'monospace',fontSize:9,color:'#4a4a66',marginTop:1}}>{item.sub}</div>
                </div>
                <span style={{marginLeft:'auto',fontFamily:'monospace',fontSize:8,color:'#00e5ff',
                  background:'rgba(0,229,255,0.1)',border:'1px solid rgba(0,229,255,0.2)',
                  borderRadius:4,padding:'2px 6px',letterSpacing:'1px'}}>SOON</span>
              </div>
            )
          ))}
        </div>

        {/* Recent projects */}
        <div style={{flex:1,overflow:'auto',padding:'16px 12px'}}>
          <div style={{fontFamily:'monospace',fontSize:9,color:'rgba(0,229,255,0.4)',letterSpacing:'3px',
            textTransform:'uppercase',marginBottom:12,paddingLeft:4}}>
            Recent Projects
          </div>
          {FAKE_PROJECTS.map(p=>(
            <div key={p.id} style={{
              padding:'14px 16px',borderRadius:10,marginBottom:8,position:'relative',
              background:'rgba(255,255,255,0.02)',border:'1px solid rgba(255,255,255,0.05)',
              cursor:'default',
            }}>
              {/* Under construction overlay */}
              <div style={{
                position:'absolute',inset:0,borderRadius:10,zIndex:2,
                background:'rgba(5,10,15,0.65)',backdropFilter:'blur(2px)',
                display:'flex',alignItems:'center',justifyContent:'center',
              }}>
                <span style={{fontFamily:'monospace',fontSize:9,color:'#00e5ff',
                  background:'rgba(0,229,255,0.08)',border:'1px solid rgba(0,229,255,0.2)',
                  borderRadius:6,padding:'4px 10px',letterSpacing:'2px'}}>
                  UNDER CONSTRUCTION
                </span>
              </div>
              <div style={{fontFamily:'Space Grotesk,sans-serif',fontWeight:600,fontSize:13,color:'#c0c0d8',marginBottom:4}}>{p.name}</div>
              <div style={{fontFamily:'monospace',fontSize:10,color:'#4a4a66',marginBottom:6}}>{p.addr}</div>
              <div style={{display:'flex',gap:8,flexWrap:'wrap'}}>
                <Tag color='#00e5ff'>{p.stories} stories</Tag>
                <Tag color='#00ff88'>{p.units} units</Tag>
                <Tag color={p.status==='review'?'#ffb300':'#7c3aed'}>{p.status}</Tag>
                <Tag color='#4a4a66'>{p.date}</Tag>
              </div>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div style={{padding:'14px 24px',borderTop:'1px solid rgba(255,255,255,0.06)',flexShrink:0}}>
          <div style={{fontFamily:'monospace',fontSize:9,color:'#2a2a44',letterSpacing:'2px',textAlign:'center'}}>
            v0.1.0 · BETA · California Multi-family
          </div>
        </div>
      </div>
    </>
  );
}

function Tag({children,color}:{children:React.ReactNode;color:string}){
  return (
    <span style={{fontFamily:'monospace',fontSize:9,color,background:`${color}15`,
      border:`1px solid ${color}30`,borderRadius:4,padding:'2px 6px'}}>
      {children}
    </span>
  );
}

// ─── Main page ──────────────────────────────────────────────────────────────
export default function LandingPage(){
  const router=useRouter();
  const [showContent,setShowContent]=useState(false);
  const [splashDone,setSplashDone]=useState(false);
  const [drawerOpen,setDrawerOpen]=useState(false);

  useEffect(()=>{
    document.documentElement.classList.remove('app-page');
    document.body.classList.remove('app-page');
    const isReload = (performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming)?.type === 'reload';
    const alreadySeen = sessionStorage.getItem('petronus_splash') === '1';
    if (alreadySeen && !isReload) {
      setSplashDone(true);
      setShowContent(true);
    }
  },[]);

  useEffect(()=>{
    if(splashDone) setShowContent(true);
  },[splashDone]);

  return (
    <div style={{background:'#050a0f',minHeight:'100vh',position:'relative',overflowX:'clip'}}>
      {!splashDone && <SplashScreen onDone={()=>{sessionStorage.setItem('petronus_splash','1');setSplashDone(true);}} />}
      <NavDrawer open={drawerOpen} onClose={()=>setDrawerOpen(false)} router={router} />
      <ParticleCanvas />

      {/* ── Sticky nav ── */}
      <nav style={{
        position:'sticky',top:0,zIndex:100,
        display:'flex',alignItems:'center',justifyContent:'space-between',
        padding:'14px 40px',
        background:'rgba(5,10,15,0.75)',
        backdropFilter:'blur(16px)',
        borderBottom:'1px solid rgba(0,229,255,0.08)',
      }}>
        {/* Logo — only one, top-left */}
        <div style={{display:'flex',alignItems:'center',gap:10}}>
          <img src="/petronus.png" alt="Petronus" style={{width:28,height:28,borderRadius:8,objectFit:'cover'}} />
          <span style={{fontFamily:'Space Grotesk,sans-serif',fontWeight:700,fontSize:16,
            background:'linear-gradient(135deg,#00e5ff,#00ff88)',WebkitBackgroundClip:'text',
            WebkitTextFillColor:'transparent',backgroundClip:'text'}}>
            Petronus
          </span>
        </div>
        {/* Hamburger → chevron ∨ */}
        <button onClick={()=>setDrawerOpen(o=>!o)} style={{
          background:'rgba(255,255,255,0.03)',border:'1px solid rgba(255,255,255,0.08)',
          borderRadius:8,padding:'9px 11px',cursor:'pointer',
          display:'flex',flexDirection:'column',alignItems:'center',justifyContent:'center',gap:4,
          transition:'border-color .2s, background .2s',
          ...(drawerOpen ? {borderColor:'rgba(0,229,255,0.3)',background:'rgba(0,229,255,0.06)'} : {}),
        }}>
          {/* Bar 1 — becomes left arm of ∨ */}
          <div style={{
            width:20, height:1.5, background: drawerOpen ? '#00e5ff' : '#8888aa',
            borderRadius:1,
            transition:'transform .3s cubic-bezier(0.22,1,0.36,1), opacity .3s, background .2s',
            transformOrigin:'right center',
            transform: drawerOpen ? 'translateY(5.5px) rotate(40deg) scaleX(0.82)' : 'none',
          }}/>
          {/* Bar 2 — fades out */}
          <div style={{
            width:20, height:1.5, background:'#8888aa',
            borderRadius:1,
            transition:'opacity .2s, transform .3s',
            opacity: drawerOpen ? 0 : 1,
            transform: drawerOpen ? 'scaleX(0)' : 'none',
          }}/>
          {/* Bar 3 — becomes right arm of ∨ */}
          <div style={{
            width:20, height:1.5, background: drawerOpen ? '#00e5ff' : '#8888aa',
            borderRadius:1,
            transition:'transform .3s cubic-bezier(0.22,1,0.36,1), opacity .3s, background .2s',
            transformOrigin:'right center',
            transform: drawerOpen ? 'translateY(-5.5px) rotate(-40deg) scaleX(0.82)' : 'none',
          }}/>
        </button>
      </nav>

      {/* ── Hero ── */}
      <section style={{
        position:'relative',zIndex:1,
        minHeight:'100vh',display:'flex',alignItems:'center',
        padding:'0 40px',gap:0,overflow:'hidden',
      }}>
        {/* Radial hero glow */}
        <div style={{
          position:'absolute',inset:0,pointerEvents:'none',
          background:'radial-gradient(ellipse 70% 60% at 30% 50%, rgba(0,229,255,0.06) 0%, transparent 65%)',
        }}/>
        <div style={{
          position:'absolute',inset:0,pointerEvents:'none',
          background:'radial-gradient(ellipse 50% 50% at 75% 50%, rgba(124,58,237,0.06) 0%, transparent 60%)',
        }}/>

        {/* Left: text */}
        <div style={{flex:'0 0 50%',paddingLeft:'4vw',zIndex:2}}>
          <div style={{
            opacity:showContent?1:0,
            transform:showContent?'translateY(0)':'translateY(20px)',
            transition:'opacity .8s ease, transform .8s ease',
          }}>
            <div style={{fontFamily:'monospace',fontSize:11,color:'#00e5ff',letterSpacing:'4px',
              textTransform:'uppercase',marginBottom:16,opacity:.8}}>
              Automated BIM Platform
            </div>
            <h1 style={{
              margin:'0 0 20px',lineHeight:1.05,
              fontFamily:'Space Grotesk,sans-serif',fontWeight:700,fontSize:'clamp(48px,6vw,80px)',
              background:'linear-gradient(135deg,#f0f0f8 0%,#00e5ff 50%,#00ff88 100%)',
              WebkitBackgroundClip:'text',WebkitTextFillColor:'transparent',backgroundClip:'text',
            }}>
              Design buildings.<br/>Not spreadsheets.
            </h1>
            <p style={{
              fontFamily:'DM Sans,sans-serif',fontSize:18,color:'#8888aa',
              lineHeight:1.7,maxWidth:480,margin:'0 0 36px',
            }}>
              Drop a pin on any California parcel. Petronus generates a complete architectural + MEP building model in under 30 seconds — site analysis, floor plans, plumbing, electrical, HVAC, and code compliance included.
            </p>
            <div style={{display:'flex',gap:14,flexWrap:'wrap'}}>
              <EnterButton onClick={()=>router.push('/app')} />
              <button onClick={()=>document.getElementById('how')?.scrollIntoView({behavior:'smooth'})}
                style={{padding:'14px 28px',borderRadius:12,fontFamily:'monospace',fontSize:13,
                  background:'transparent',border:'1px solid rgba(255,255,255,0.12)',
                  color:'#8888aa',cursor:'pointer',transition:'all .2s',}}>
                See how it works
              </button>
            </div>
            <div style={{display:'flex',gap:32,marginTop:48}}>
              {[['< 30s','Generation time'],['50+','Code checks'],['3','Massing options'],['Full','MEP systems']].map(([val,lbl])=>(
                <div key={lbl}>
                  <div style={{fontFamily:'Space Grotesk,sans-serif',fontWeight:700,fontSize:22,
                    background:'linear-gradient(135deg,#00e5ff,#00ff88)',
                    WebkitBackgroundClip:'text',WebkitTextFillColor:'transparent',backgroundClip:'text'}}>
                    {val}
                  </div>
                  <div style={{fontFamily:'monospace',fontSize:10,color:'#4a6a7a',marginTop:2,letterSpacing:'1px'}}>{lbl}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Right: 3D building wireframe */}
        <div style={{
          flex:'0 0 50%',display:'flex',alignItems:'center',justifyContent:'center',
          opacity:showContent?1:0,transition:'opacity 1.2s ease .3s',
        }}>
          <BuildingWireframe />
        </div>
      </section>

      {/* ── Features ── */}
      <section style={{position:'relative',zIndex:1,padding:'100px 40px',maxWidth:1200,margin:'0 auto'}}>
        <FadeIn>
          <div style={{textAlign:'center',marginBottom:64}}>
            <div style={{fontFamily:'monospace',fontSize:11,color:'#00e5ff',letterSpacing:'4px',textTransform:'uppercase',marginBottom:12,opacity:.8}}>
              Capabilities
            </div>
            <h2 style={{fontFamily:'Space Grotesk,sans-serif',fontWeight:700,fontSize:'clamp(28px,4vw,44px)',margin:0,color:'#f0f0f8'}}>
              Everything in one pipeline
            </h2>
          </div>
        </FadeIn>
        <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(260px,1fr))',gap:20}}>
          {FEATURES.map((f,i)=>(
            <FadeIn key={f.title} delay={i*.08}>
              <FeatureCard {...f} />
            </FadeIn>
          ))}
        </div>
      </section>

      {/* ── How it works ── */}
      <section id="how" style={{position:'relative',zIndex:1,padding:'100px 40px',
        background:'linear-gradient(180deg,transparent,rgba(0,229,255,0.02) 40%,transparent)'}}>
        <div style={{maxWidth:900,margin:'0 auto'}}>
          <FadeIn>
            <div style={{textAlign:'center',marginBottom:72}}>
              <div style={{fontFamily:'monospace',fontSize:11,color:'#00ff88',letterSpacing:'4px',textTransform:'uppercase',marginBottom:12,opacity:.8}}>
                Workflow
              </div>
              <h2 style={{fontFamily:'Space Grotesk,sans-serif',fontWeight:700,fontSize:'clamp(28px,4vw,44px)',margin:0,color:'#f0f0f8'}}>
                From parcel to BIM in 4 steps
              </h2>
            </div>
          </FadeIn>
          <div style={{position:'relative'}}>
            {/* Connecting line */}
            <div style={{
              position:'absolute',left:'calc(50% - .5px)',top:32,bottom:32,
              width:1,background:'linear-gradient(180deg,rgba(0,229,255,0.3),rgba(0,255,136,0.3))',
              zIndex:0,
            }}/>
            {STEPS.map((s,i)=>(
              <FadeIn key={s.title} delay={i*.1}>
                <StepCard step={s} index={i} />
              </FadeIn>
            ))}
          </div>
        </div>
      </section>

      {/* ── Terminal demo section ── */}
      <section style={{position:'relative',zIndex:1,padding:'100px 40px',
        background:'linear-gradient(180deg,transparent,rgba(124,58,237,0.03) 50%,transparent)'}}>
        <div style={{maxWidth:1100,margin:'0 auto',display:'grid',gridTemplateColumns:'1fr 1fr',gap:64,alignItems:'center'}}>
          <FadeIn>
            <div>
              <div style={{fontFamily:'monospace',fontSize:11,color:'#7c3aed',letterSpacing:'4px',textTransform:'uppercase',marginBottom:16,opacity:.8}}>Live Pipeline</div>
              <h2 style={{fontFamily:'Space Grotesk,sans-serif',fontWeight:700,fontSize:'clamp(26px,3.5vw,40px)',margin:'0 0 20px',color:'#f0f0f8'}}>
                Watch the model build itself
              </h2>
              <p style={{fontFamily:'DM Sans,sans-serif',fontSize:15,color:'#6a6a88',lineHeight:1.8,margin:'0 0 32px'}}>
                Every stage streams in real time — site data, massing, rooms, MEP routing, compliance. You see exactly what's happening and why.
              </p>
              <div style={{display:'flex',flexDirection:'column',gap:12}}>
                {[
                  {step:'01',label:'Site context',detail:'OSM + FEMA + USGS in parallel',color:'#00e5ff'},
                  {step:'02',label:'Massing',detail:'3 options, scored by priority',color:'#00ff88'},
                  {step:'03',label:'Floorplan',detail:'Units clipped to actual footprint',color:'#7c3aed'},
                  {step:'04',label:'MEP routing',detail:'Plumbing, electrical, HVAC',color:'#ffb300'},
                  {step:'05',label:'Compliance',detail:'50+ CA Building Code checks',color:'#f472b6'},
                ].map((item)=>(
                  <div key={item.step} style={{display:'flex',alignItems:'center',gap:16}}>
                    <div style={{fontFamily:'monospace',fontSize:10,color:item.color,opacity:.6,flexShrink:0,width:24}}>{item.step}</div>
                    <div style={{flex:1,height:1,background:`linear-gradient(90deg,${item.color}40,transparent)`}}/>
                    <div style={{fontFamily:'monospace',fontSize:12,color:'#c0c0d8',flexShrink:0}}>{item.label}</div>
                    <div style={{fontFamily:'monospace',fontSize:10,color:'#4a4a66',flexShrink:0,maxWidth:180,textAlign:'right'}}>{item.detail}</div>
                  </div>
                ))}
              </div>
            </div>
          </FadeIn>
          <FadeIn delay={.15}>
            <TerminalBlock />
          </FadeIn>
        </div>
      </section>

      {/* ── Stats bar ── */}
      <section style={{position:'relative',zIndex:1,padding:'60px 40px'}}>
        <FadeIn>
          <div style={{
            maxWidth:1000,margin:'0 auto',display:'grid',
            gridTemplateColumns:'repeat(4,1fr)',gap:1,
            border:'1px solid rgba(255,255,255,0.05)',borderRadius:20,overflow:'hidden',
          }}>
            {[
              {val:'< 30s',label:'Full generation',sub:'from pin to 3D model',color:'#00e5ff'},
              {val:'50+',label:'Code checks',sub:'CBC, Title 24, ASCE 7-22',color:'#00ff88'},
              {val:'3',label:'Massing options',sub:'rectangle · L-shape · bar',color:'#7c3aed'},
              {val:'100%',label:'CA-specific',sub:'built for California parcels',color:'#ffb300'},
            ].map((s,i)=>(
              <div key={s.label} style={{
                padding:'36px 28px',textAlign:'center',
                background:i%2===0?'rgba(255,255,255,0.015)':'rgba(255,255,255,0.008)',
                borderRight:i<3?'1px solid rgba(255,255,255,0.05)':'none',
              }}>
                <div style={{
                  fontFamily:'Space Grotesk,sans-serif',fontWeight:700,fontSize:36,
                  background:`linear-gradient(135deg,${s.color},${s.color}99)`,
                  WebkitBackgroundClip:'text',WebkitTextFillColor:'transparent',backgroundClip:'text',
                  marginBottom:8,
                }}>{s.val}</div>
                <div style={{fontFamily:'Space Grotesk,sans-serif',fontWeight:600,fontSize:14,color:'#c0c0d8',marginBottom:4}}>{s.label}</div>
                <div style={{fontFamily:'monospace',fontSize:10,color:'#4a4a66',letterSpacing:'0.5px'}}>{s.sub}</div>
              </div>
            ))}
          </div>
        </FadeIn>
      </section>

      {/* ── Why Petronus / comparison ── */}
      <section style={{position:'relative',zIndex:1,padding:'100px 40px',
        background:'linear-gradient(180deg,transparent,rgba(0,255,136,0.02) 50%,transparent)'}}>
        <div style={{maxWidth:1100,margin:'0 auto'}}>
          <FadeIn>
            <div style={{textAlign:'center',marginBottom:64}}>
              <div style={{fontFamily:'monospace',fontSize:11,color:'#00ff88',letterSpacing:'4px',textTransform:'uppercase',marginBottom:12,opacity:.8}}>Why Petronus</div>
              <h2 style={{fontFamily:'Space Grotesk,sans-serif',fontWeight:700,fontSize:'clamp(28px,4vw,44px)',margin:0,color:'#f0f0f8'}}>
                Replace the manual process
              </h2>
            </div>
          </FadeIn>
          <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:24}}>
            <FadeIn delay={0}>
              <div style={{padding:32,borderRadius:20,border:'1px solid rgba(255,68,68,0.2)',background:'rgba(255,68,68,0.03)'}}>
                <div style={{fontFamily:'monospace',fontSize:11,color:'#ff4444',letterSpacing:'3px',textTransform:'uppercase',marginBottom:24,opacity:.8}}>Traditional workflow</div>
                {[
                  'Days of manual site research',
                  'Schematic massing in Revit or SketchUp',
                  'Separate MEP consultant coordination',
                  'Code consultant for compliance review',
                  'Multiple revision cycles per schema',
                  'No real-time neighbor data',
                ].map(item=>(
                  <div key={item} style={{display:'flex',alignItems:'center',gap:12,marginBottom:14}}>
                    <div style={{width:16,height:16,borderRadius:'50%',border:'1px solid #ff444444',display:'flex',alignItems:'center',justifyContent:'center',flexShrink:0}}>
                      <div style={{width:6,height:1.5,background:'#ff4444',borderRadius:1}}/>
                    </div>
                    <span style={{fontFamily:'DM Sans,sans-serif',fontSize:14,color:'#5a5a7a'}}>{item}</span>
                  </div>
                ))}
              </div>
            </FadeIn>
            <FadeIn delay={.1}>
              <div style={{padding:32,borderRadius:20,border:'1px solid rgba(0,229,255,0.2)',background:'rgba(0,229,255,0.03)'}}>
                <div style={{fontFamily:'monospace',fontSize:11,color:'#00e5ff',letterSpacing:'3px',textTransform:'uppercase',marginBottom:24,opacity:.8}}>With Petronus</div>
                {[
                  'Site data fetched instantly from OSM + FEMA',
                  '3 massing options generated in seconds',
                  'MEP routing runs inside the same pipeline',
                  '50+ CBC checks run at generation time',
                  'One click → full BIM-ready model',
                  'Real OSM neighbor buildings in 3D',
                ].map(item=>(
                  <div key={item} style={{display:'flex',alignItems:'center',gap:12,marginBottom:14}}>
                    <div style={{width:16,height:16,borderRadius:'50%',border:'1px solid #00e5ff44',display:'flex',alignItems:'center',justifyContent:'center',flexShrink:0}}>
                      <div style={{width:6,height:6,background:'#00e5ff',borderRadius:'50%'}}/>
                    </div>
                    <span style={{fontFamily:'DM Sans,sans-serif',fontSize:14,color:'#8888aa'}}>{item}</span>
                  </div>
                ))}
              </div>
            </FadeIn>
          </div>
        </div>
      </section>

      {/* ── Tech stack ── */}
      <section style={{position:'relative',zIndex:1,padding:'80px 40px'}}>
        <div style={{maxWidth:1100,margin:'0 auto'}}>
          <FadeIn>
            <div style={{textAlign:'center',marginBottom:52}}>
              <div style={{fontFamily:'monospace',fontSize:11,color:'#7c3aed',letterSpacing:'4px',textTransform:'uppercase',marginBottom:12,opacity:.8}}>Built With</div>
              <h2 style={{fontFamily:'Space Grotesk,sans-serif',fontWeight:700,fontSize:'clamp(24px,3vw,36px)',margin:0,color:'#f0f0f8'}}>
                A real engineering stack
              </h2>
            </div>
          </FadeIn>
          <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(200px,1fr))',gap:16}}>
            {[
              {name:'FastAPI',role:'Backend pipeline',color:'#00e5ff',icon:'⚡'},
              {name:'Next.js 14',role:'App Router + SSR',color:'#f0f0f8',icon:'▲'},
              {name:'Three.js',role:'3D model viewer',color:'#00ff88',icon:'◉'},
              {name:'MapLibre GL',role:'Vector map tiles',color:'#7c3aed',icon:'🗺'},
              {name:'Shapely',role:'Parcel geometry',color:'#ffb300',icon:'◈'},
              {name:'OpenStreetMap',role:'Neighbor buildings',color:'#f472b6',icon:'◎'},
              {name:'USGS + FEMA',role:'Seismic + flood data',color:'#34d399',icon:'◇'},
              {name:'wttr.in',role:'Real-time weather',color:'#60a5fa',icon:'⛅'},
            ].map((t,i)=>(
              <FadeIn key={t.name} delay={i*.05}>
                <div style={{
                  padding:'20px 22px',borderRadius:14,
                  border:'1px solid rgba(255,255,255,0.06)',
                  background:'rgba(255,255,255,0.02)',
                  transition:'all .2s',
                }}>
                  <div style={{fontSize:20,marginBottom:10}}>{t.icon}</div>
                  <div style={{
                    fontFamily:'Space Grotesk,sans-serif',fontWeight:600,fontSize:15,
                    color:t.color,marginBottom:4,
                  }}>{t.name}</div>
                  <div style={{fontFamily:'monospace',fontSize:10,color:'#4a4a66',letterSpacing:'.5px'}}>{t.role}</div>
                </div>
              </FadeIn>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA banner ── */}
      <section style={{position:'relative',zIndex:1,padding:'80px 40px'}}>
        <FadeIn>
          <div style={{
            maxWidth:800,margin:'0 auto',padding:'64px 48px',borderRadius:24,textAlign:'center',
            background:'linear-gradient(135deg,rgba(0,229,255,0.06),rgba(0,255,136,0.04),rgba(124,58,237,0.06))',
            border:'1px solid rgba(0,229,255,0.15)',
            boxShadow:'0 0 80px rgba(0,229,255,0.06)',
          }}>
            <div style={{fontFamily:'monospace',fontSize:11,color:'#00e5ff',letterSpacing:'4px',textTransform:'uppercase',marginBottom:16,opacity:.7}}>Ready to build</div>
            <h2 style={{fontFamily:'Space Grotesk,sans-serif',fontWeight:700,fontSize:'clamp(28px,4vw,48px)',margin:'0 0 20px',
              background:'linear-gradient(135deg,#f0f0f8,#00e5ff)',
              WebkitBackgroundClip:'text',WebkitTextFillColor:'transparent',backgroundClip:'text'}}>
              Drop your first pin
            </h2>
            <p style={{fontFamily:'DM Sans,sans-serif',fontSize:16,color:'#6a6a88',lineHeight:1.7,margin:'0 0 36px',maxWidth:480,marginLeft:'auto',marginRight:'auto'}}>
              No login. No setup. Click any California parcel and get a full building model in under 30 seconds.
            </p>
            <EnterButton onClick={()=>router.push('/app')} />
          </div>
        </FadeIn>
      </section>

      {/* ── Visual divider: luminous glow bar ── */}
      <div style={{
        height:1,margin:'0 40px',
        background:'linear-gradient(90deg,transparent,rgba(0,229,255,0.4),rgba(0,255,136,0.4),transparent)',
        boxShadow:'0 0 20px rgba(0,229,255,0.15)',
      }}/>

      {/* ── About / Footer ── */}
      <footer style={{position:'relative',zIndex:1,padding:'80px 40px 48px',
        background:'linear-gradient(180deg,transparent,rgba(0,5,10,0.6))'}}>
        <div style={{maxWidth:1100,margin:'0 auto'}}>
          <div style={{display:'grid',gridTemplateColumns:'2fr 1fr 1fr',gap:48,marginBottom:64}}>
            {/* About */}
            <FadeIn>
              <div>
                <div style={{display:'flex',alignItems:'center',gap:10,marginBottom:20}}>
                  <img src="/petronus.png" alt="Petronus" style={{width:36,height:36,borderRadius:10,objectFit:'cover'}} />
                  <span style={{fontFamily:'Space Grotesk,sans-serif',fontWeight:700,fontSize:20,
                    background:'linear-gradient(135deg,#00e5ff,#00ff88)',
                    WebkitBackgroundClip:'text',WebkitTextFillColor:'transparent',backgroundClip:'text'}}>
                    Petronus
                  </span>
                </div>
                <p style={{fontFamily:'DM Sans,sans-serif',fontSize:14,color:'#6a6a88',lineHeight:1.8,maxWidth:360,margin:'0 0 20px'}}>
                  Petronus is an automated BIM platform built for California multi-family residential development. We replace weeks of manual drafting with an AI pipeline that generates code-compliant building models from a parcel pin.
                </p>
                <p style={{fontFamily:'DM Sans,sans-serif',fontSize:13,color:'#4a4a66',lineHeight:1.7,maxWidth:360,margin:0}}>
                  Built for architects, developers, and engineers who want to move fast without sacrificing quality or compliance.
                </p>
              </div>
            </FadeIn>
            {/* Platform */}
            <FadeIn delay={.1}>
              <div>
                <div style={{fontFamily:'monospace',fontSize:10,color:'#00e5ff',letterSpacing:'3px',textTransform:'uppercase',marginBottom:20,opacity:.7}}>Platform</div>
                {['Site Analysis','Massing Generator','Floorplan Layout','MEP Routing','Code Compliance','Facade Design'].map(l=>(
                  <div key={l} style={{fontFamily:'DM Sans,sans-serif',fontSize:13,color:'#5a5a7a',marginBottom:10,cursor:'default'}}>{l}</div>
                ))}
              </div>
            </FadeIn>
            {/* Built for */}
            <FadeIn delay={.15}>
              <div>
                <div style={{fontFamily:'monospace',fontSize:10,color:'#00ff88',letterSpacing:'3px',textTransform:'uppercase',marginBottom:20,opacity:.7}}>Built For</div>
                {['California Residential','Multi-family Projects','CBC Compliance','R-2 Occupancy','Title 24','ASCE 7-22'].map(l=>(
                  <div key={l} style={{fontFamily:'DM Sans,sans-serif',fontSize:13,color:'#5a5a7a',marginBottom:10,cursor:'default'}}>{l}</div>
                ))}
              </div>
            </FadeIn>
          </div>
          {/* Bottom bar */}
          <div style={{
            display:'flex',alignItems:'center',justifyContent:'space-between',flexWrap:'wrap',gap:16,
            paddingTop:24,borderTop:'1px solid rgba(255,255,255,0.05)',
          }}>
            <span style={{fontFamily:'monospace',fontSize:11,color:'#2a2a44'}}>
              © 2025 Petronus · All rights reserved
            </span>
            <span style={{fontFamily:'monospace',fontSize:10,color:'#2a2a44',letterSpacing:'2px'}}>
              v0.1.0 · BETA · California Multi-family Residential
            </span>
          </div>
        </div>
      </footer>
    </div>
  );
}

// ─── Animated terminal block ────────────────────────────────────────────────
function TerminalBlock() {
  const lines = [
    {text:'$ petronus generate --site "Fremont, CA"', color:'#00e5ff', delay:0},
    {text:'  ↳ Fetching site context…', color:'#8888aa', delay:400},
    {text:'  ✓ Parcel: 5,840 sqft  Flood: X  Seismic: D', color:'#00ff88', delay:900},
    {text:'  ✓ Terrain: slope 2.1% (1.2°) — flat', color:'#00ff88', delay:1300},
    {text:'  ↳ Generating 3 massing options…', color:'#8888aa', delay:1700},
    {text:'  ✓ Option A: Rectangle  Score: 87', color:'#00ff88', delay:2200},
    {text:'  ✓ Option B: L-Shape    Score: 74', color:'#00ff88', delay:2500},
    {text:'  ✓ Option C: Bar        Score: 81', color:'#00ff88', delay:2800},
    {text:'  ↳ Generating floorplan (14 rooms)…', color:'#8888aa', delay:3200},
    {text:'  ✓ 6 units · corridor · stair core', color:'#00ff88', delay:3700},
    {text:'  ↳ Routing MEP systems…', color:'#8888aa', delay:4100},
    {text:'  ✓ 12 plumbing · 18 electrical · 9 HVAC', color:'#00ff88', delay:4600},
    {text:'  ↳ Running compliance checks…', color:'#8888aa', delay:5000},
    {text:'  ✓ 0 errors · 2 warnings · CBC 2022', color:'#00ff88', delay:5500},
    {text:'  ✓ Model ready  [27.4s]', color:'#7c3aed', delay:6000},
  ];
  const [visCount, setVisCount] = useState(0);
  useEffect(() => {
    const timers = lines.map((l, i) =>
      setTimeout(() => setVisCount(n => Math.max(n, i + 1)), l.delay + 800)
    );
    return () => timers.forEach(clearTimeout);
  }, []);
  return (
    <div style={{
      background:'#080c10',border:'1px solid rgba(0,229,255,0.15)',borderRadius:16,
      padding:'24px 28px',fontFamily:'JetBrains Mono,monospace',fontSize:12,lineHeight:1.8,
      boxShadow:'0 0 40px rgba(0,229,255,0.06)',
    }}>
      <div style={{display:'flex',gap:7,marginBottom:18}}>
        {['#ff5f57','#ffbd2e','#28c840'].map(c=>(
          <div key={c} style={{width:11,height:11,borderRadius:'50%',background:c}}/>
        ))}
        <span style={{fontFamily:'JetBrains Mono,monospace',fontSize:11,color:'#3a3a5a',marginLeft:8}}>
          petronus — terminal
        </span>
      </div>
      {lines.slice(0, visCount).map((l, i) => (
        <div key={i} style={{color:l.color,opacity: i === visCount-1 ? 1 : 0.9}}>
          {l.text}
          {i === visCount-1 && visCount < lines.length && (
            <span style={{borderRight:'1.5px solid #00e5ff',marginLeft:2,animation:'blink 1s step-end infinite'}}>&nbsp;</span>
          )}
        </div>
      ))}
      {visCount === 0 && <div style={{color:'#3a3a5a'}}>_</div>}
    </div>
  );
}

// ─── Enter button with hover state ─────────────────────────────────────────
function EnterButton({onClick}:{onClick:()=>void}){
  const [h,setH]=useState(false);
  return (
    <button onClick={onClick} onMouseEnter={()=>setH(true)} onMouseLeave={()=>setH(false)}
      style={{
        padding:'14px 32px',borderRadius:12,fontFamily:'monospace',fontSize:13,fontWeight:600,
        cursor:'pointer',letterSpacing:'.5px',transition:'all .2s ease',
        background:'linear-gradient(135deg,rgba(0,229,255,0.18),rgba(0,255,136,0.12))',
        border:`1px solid ${h?'rgba(0,229,255,0.8)':'rgba(0,229,255,0.4)'}`,
        color:'#00e5ff',
        boxShadow:h?'0 0 40px rgba(0,229,255,0.3),0 0 15px rgba(0,229,255,0.15)':'0 0 20px rgba(0,229,255,0.08)',
      }}>
      Launch Petronus →
    </button>
  );
}

// ─── Feature card ───────────────────────────────────────────────────────────
function FeatureCard({icon,title,desc,color}:{icon:string;title:string;desc:string;color:string}){
  const [h,setH]=useState(false);
  return (
    <div onMouseEnter={()=>setH(true)} onMouseLeave={()=>setH(false)}
      style={{
        padding:28,borderRadius:16,transition:'all .25s ease',cursor:'default',
        background:h?'rgba(0,229,255,0.04)':'rgba(255,255,255,0.02)',
        border:`1px solid ${h?color+'55':'rgba(255,255,255,0.06)'}`,
        boxShadow:h?`0 0 30px ${color}18`:'none',
        transform:h?'translateY(-3px)':'none',
      }}>
      <div style={{fontSize:28,marginBottom:16}}>{icon}</div>
      <h3 style={{fontFamily:'Space Grotesk,sans-serif',fontWeight:600,fontSize:17,
        color:'#e0e0f0',margin:'0 0 10px'}}>{title}</h3>
      <p style={{fontFamily:'DM Sans,sans-serif',fontSize:13,color:'#6a6a88',
        lineHeight:1.75,margin:0}}>{desc}</p>
    </div>
  );
}

// ─── Step card ──────────────────────────────────────────────────────────────
function StepCard({step,index}:{step:typeof STEPS[0];index:number}){
  const isLeft=index%2===0;
  return (
    <div style={{
      display:'flex',alignItems:'flex-start',gap:24,marginBottom:48,
      flexDirection:isLeft?'row':'row-reverse',
    }}>
      <div style={{flex:'0 0 calc(50% - 32px)',textAlign:isLeft?'right':'left'}}>
        <div style={{fontFamily:'monospace',fontSize:10,color:step.color,letterSpacing:'3px',
          textTransform:'uppercase',marginBottom:8,opacity:.8}}>{step.label}</div>
        <h3 style={{fontFamily:'Space Grotesk,sans-serif',fontWeight:700,fontSize:20,
          color:'#e0e0f0',margin:'0 0 10px'}}>{step.title}</h3>
        <p style={{fontFamily:'DM Sans,sans-serif',fontSize:14,color:'#6a6a88',
          lineHeight:1.7,margin:0}}>{step.desc}</p>
      </div>
      {/* Center dot */}
      <div style={{
        flex:'0 0 28px',width:28,height:28,borderRadius:'50%',
        background:`radial-gradient(circle,${step.color}33,transparent 70%)`,
        border:`1.5px solid ${step.color}`,
        display:'flex',alignItems:'center',justifyContent:'center',
        fontFamily:'monospace',fontWeight:700,fontSize:11,color:step.color,
        zIndex:1,marginTop:4,flexShrink:0,
        boxShadow:`0 0 16px ${step.color}44`,
      }}>
        {index+1}
      </div>
      <div style={{flex:'0 0 calc(50% - 32px)'}}/>
    </div>
  );
}

// ─── Data ───────────────────────────────────────────────────────────────────
const FEATURES = [
  {icon:'🌍',title:'Site Intelligence',color:'#00e5ff',
    desc:'Parcel analysis, FEMA flood zones, USGS seismic data, OSM neighbor constraints, terrain slope, and legal feasibility — all fetched automatically.'},
  {icon:'🏗️',title:'Automated Massing',color:'#00ff88',
    desc:'Three massing options (rectangle, L-shape, bar) generated from your parcel envelope, scored on cost, compactness, and daylight.'},
  {icon:'📐',title:'Floor Plan Layout',color:'#7c3aed',
    desc:'Unit mix, corridor spine, stair core, and sub-room placement packed into the chosen massing — ready for permit review.'},
  {icon:'⚡',title:'MEP Routing',color:'#ffb300',
    desc:'Complete plumbing risers and branches, electrical panels and conduit runs, and HVAC duct layouts — all connected and code-aware.'},
  {icon:'🏛️',title:'Facade Design',color:'#f472b6',
    desc:'Windows sized and spaced per floor, dark frames, roof parapet — styled to match surrounding OSM building materials and colors.'},
  {icon:'✅',title:'Code Compliance',color:'#34d399',
    desc:'50+ California Building Code checks run at generation time: egress, fire separation, structural, energy, and accessibility flags.'},
];

const STEPS = [
  {label:'Step 01',title:'Drop a pin',color:'#00e5ff',
    desc:'Click anywhere on the map to select a parcel. Petronus fetches the site boundary, flood zone, seismic data, neighbor buildings, and terrain elevation automatically.'},
  {label:'Step 02',title:'Set parameters',color:'#00ff88',
    desc:'Choose stories, unit count, structural system (wood / steel / concrete), HVAC type, and your priority — cost, speed, or daylight.'},
  {label:'Step 03',title:'Generate',color:'#7c3aed',
    desc:'Hit Generate. In under 30 seconds the full pipeline runs: massing → floorplan → MEP → compliance → facade. All connected, all to scale.'},
  {label:'Step 04',title:'Review & export',color:'#ffb300',
    desc:'Orbit the 3D model, toggle MEP layers, review compliance issues, pick your massing option, and export to BIM.'},
];
