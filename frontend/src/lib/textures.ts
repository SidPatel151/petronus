/**
 * Procedural PBR-ish texture generator for building materials.
 * All textures are created on a canvas and cached — no external assets needed.
 */
import * as THREE from 'three';

const _cache = new Map<string, THREE.Texture>();

// ── Brick ───────────────────────────────────────────────────────────────────
function createBrickTexture(): THREE.Texture {
  const W = 512, H = 512;
  const canvas = document.createElement('canvas');
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext('2d')!;

  ctx.fillStyle = '#7a6252'; // mortar
  ctx.fillRect(0, 0, W, H);

  const bW = 52, bH = 22, gap = 4;
  const rows = Math.ceil(H / (bH + gap)) + 1;
  for (let row = 0; row < rows; row++) {
    const offset = (row % 2) ? (bW + gap) / 2 : 0;
    const y = row * (bH + gap);
    const cols = Math.ceil((W + bW) / (bW + gap)) + 1;
    for (let col = 0; col < cols; col++) {
      const x = col * (bW + gap) - offset;
      const v = (Math.random() - 0.5) * 28;
      const r = clamp(181 + v, 130, 220);
      const g = clamp(100 + v * 0.55, 55, 145);
      const b = clamp(29  + v * 0.3,  12, 65);
      ctx.fillStyle = `rgb(${r|0},${g|0},${b|0})`;
      ctx.fillRect(x + gap / 2, y + gap / 2, bW - gap / 2, bH - gap / 2);
      // bottom shadow on brick
      ctx.fillStyle = 'rgba(0,0,0,0.18)';
      ctx.fillRect(x + gap / 2, y + bH - 3, bW - gap / 2, 3);
    }
  }
  return makeTexture(canvas, 5, 5);
}

// ── Concrete ────────────────────────────────────────────────────────────────
function createConcreteTexture(): THREE.Texture {
  const W = 512, H = 512;
  const canvas = document.createElement('canvas');
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext('2d')!;

  // Dark form-cast concrete base
  ctx.fillStyle = '#6b7280';
  ctx.fillRect(0, 0, W, H);

  // Heavy formwork panel joints (every 120px horizontal, 160px vertical)
  ctx.strokeStyle = '#374151';
  ctx.lineWidth = 3;
  for (let x = 0; x <= W; x += 120) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
  }
  for (let y = 0; y <= H; y += 160) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
  }

  // Tie hole marks at panel intersections
  ctx.fillStyle = '#1f2937';
  for (let x = 0; x <= W; x += 120) {
    for (let y = 0; y <= H; y += 160) {
      ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2); ctx.fill();
    }
  }

  // Subtle aggregate variation within panels
  for (let x = 0; x < W; x += 120) {
    for (let y = 0; y < H; y += 160) {
      const v = (Math.random() - 0.5) * 20;
      ctx.fillStyle = `rgba(${107+v|0},${114+v|0},${128+v|0},0.3)`;
      ctx.fillRect(x + 4, y + 4, 112, 152);
    }
  }

  // Pour lines (horizontal streaks from settling)
  for (let y = 20; y < H; y += 30 + Math.random() * 20) {
    ctx.fillStyle = `rgba(0,0,0,${0.03 + Math.random() * 0.04})`;
    ctx.fillRect(0, y, W, 1 + Math.random() * 2);
  }

  addNoise(ctx, W, H, 10);
  return makeTexture(canvas, 3, 4);
}

// ── Wood siding ─────────────────────────────────────────────────────────────
function createWoodTexture(): THREE.Texture {
  const W = 512, H = 512;
  const canvas = document.createElement('canvas');
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext('2d')!;

  const pH = 28; // plank height
  const planks = Math.ceil(H / pH) + 1;
  for (let p = 0; p < planks; p++) {
    const y = p * pH;
    const v = (Math.random() - 0.5) * 24;
    const r = clamp(166 + v, 100, 210);
    const g = clamp(124 + v * 0.85, 65, 165);
    const b = clamp(82  + v * 0.65, 35, 115);
    ctx.fillStyle = `rgb(${r|0},${g|0},${b|0})`;
    ctx.fillRect(0, y, W, pH - 2);

    // Grain streaks
    ctx.strokeStyle = 'rgba(0,0,0,0.04)';
    ctx.lineWidth = 1;
    for (let i = 0; i < 5; i++) {
      const gy = y + Math.random() * pH;
      ctx.beginPath();
      ctx.moveTo(0, gy);
      ctx.bezierCurveTo(W * 0.3, gy + (Math.random()-0.5)*3, W * 0.7, gy + (Math.random()-0.5)*3, W, gy + (Math.random()-0.5)*2);
      ctx.stroke();
    }
    // Shadow + highlight per plank
    ctx.fillStyle = 'rgba(0,0,0,0.22)';
    ctx.fillRect(0, y + pH - 3, W, 3);
    ctx.fillStyle = 'rgba(255,255,255,0.07)';
    ctx.fillRect(0, y, W, 2);
  }
  return makeTexture(canvas, 3, 9);
}

// ── Stucco ──────────────────────────────────────────────────────────────────
function createStuccoTexture(): THREE.Texture {
  const W = 512, H = 512;
  const canvas = document.createElement('canvas');
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext('2d')!;

  ctx.fillStyle = '#d6cbb8';
  ctx.fillRect(0, 0, W, H);
  addNoise(ctx, W, H, 16);

  // Fine stipple
  for (let i = 0; i < 5000; i++) {
    const x = Math.random() * W, y = Math.random() * H;
    ctx.fillStyle = `rgba(0,0,0,${Math.random() * 0.05})`;
    ctx.beginPath();
    ctx.arc(x, y, Math.random() * 1.2, 0, Math.PI * 2);
    ctx.fill();
  }
  return makeTexture(canvas, 5, 5);
}

// ── Steel / curtain wall ────────────────────────────────────────────────────
function createSteelTexture(): THREE.Texture {
  const W = 256, H = 256;
  const canvas = document.createElement('canvas');
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext('2d')!;

  ctx.fillStyle = '#5a6a7a';
  ctx.fillRect(0, 0, W, H);

  // Panel grid
  const pW = 64, pH = 48;
  ctx.strokeStyle = '#1e293b';
  ctx.lineWidth = 2;
  for (let x = 0; x <= W; x += pW) { ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,H); ctx.stroke(); }
  for (let y = 0; y <= H; y += pH) { ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(W,y); ctx.stroke(); }

  // Highlight gradient per panel
  for (let x = 0; x < W; x += pW) {
    for (let y = 0; y < H; y += pH) {
      const grad = ctx.createLinearGradient(x, y, x, y + pH);
      grad.addColorStop(0,   'rgba(255,255,255,0.07)');
      grad.addColorStop(0.5, 'rgba(255,255,255,0.01)');
      grad.addColorStop(1,   'rgba(0,0,0,0.04)');
      ctx.fillStyle = grad;
      ctx.fillRect(x + 2, y + 2, pW - 4, pH - 4);
    }
  }
  addNoise(ctx, W, H, 8);
  return makeTexture(canvas, 6, 6);
}

// ── Stone / masonry ─────────────────────────────────────────────────────────
function createStoneTexture(): THREE.Texture {
  const W = 512, H = 512;
  const canvas = document.createElement('canvas');
  canvas.width = W; canvas.height = H;
  const ctx = canvas.getContext('2d')!;

  ctx.fillStyle = '#8a7d70'; // mortar
  ctx.fillRect(0, 0, W, H);

  // Irregular stone blocks (random sizes)
  const seed = 42;
  let y = 4;
  while (y < H) {
    const rowH = 28 + Math.floor(Math.sin(y * 0.1 + seed) * 8 + 8);
    let x = 4;
    while (x < W) {
      const bW = 40 + Math.floor(Math.cos(x * 0.07 + y * 0.05) * 15 + 15);
      const v = (Math.sin(x * 0.13 + y * 0.17) * 0.5 + 0.5) * 30 - 15;
      const r = clamp(184 + v, 120, 220);
      const g = clamp(169 + v * 0.9, 110, 200);
      const b = clamp(160 + v * 0.8, 100, 190);
      ctx.fillStyle = `rgb(${r|0},${g|0},${b|0})`;
      ctx.fillRect(x, y, bW - 4, rowH - 4);
      // Inner shadow
      ctx.fillStyle = 'rgba(0,0,0,0.1)';
      ctx.fillRect(x, y + rowH - 6, bW - 4, 3);
      x += bW;
    }
    y += rowH;
  }
  addNoise(ctx, W, H, 10);
  return makeTexture(canvas, 4, 4);
}

// ── Helpers ─────────────────────────────────────────────────────────────────
function clamp(v: number, min: number, max: number) {
  return Math.min(max, Math.max(min, v));
}

function addNoise(ctx: CanvasRenderingContext2D, W: number, H: number, strength: number) {
  const img = ctx.getImageData(0, 0, W, H);
  const d = img.data;
  for (let i = 0; i < d.length; i += 4) {
    const n = (Math.random() - 0.5) * strength;
    d[i]   = clamp(d[i]   + n, 0, 255);
    d[i+1] = clamp(d[i+1] + n, 0, 255);
    d[i+2] = clamp(d[i+2] + n, 0, 255);
  }
  ctx.putImageData(img, 0, 0);
}

function makeTexture(canvas: HTMLCanvasElement, repeatX: number, repeatY: number): THREE.Texture {
  const tex = new THREE.CanvasTexture(canvas);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  tex.repeat.set(repeatX, repeatY);
  tex.needsUpdate = true;
  return tex;
}

// ── Public API ───────────────────────────────────────────────────────────────
const CREATORS: Record<string, () => THREE.Texture> = {
  brick:    createBrickTexture,
  concrete: createConcreteTexture,
  wood:     createWoodTexture,
  stucco:   createStuccoTexture,
  steel:    createSteelTexture,
  stone:    createStoneTexture,
};

/** Get (or lazily create) a procedural texture by name. */
export function getTexture(name: string): THREE.Texture {
  if (!_cache.has(name)) _cache.set(name, CREATORS[name]?.() ?? createStuccoTexture());
  return _cache.get(name)!;
}

/**
 * Decide which texture to use given structural system + dominant neighbor material.
 * Returns { texName, roughness, metalness }
 */
export function resolveTexture(structuralSystem: string, facadeMaterial = ''): {
  texName: string; roughness: number; metalness: number;
} {
  const mat = facadeMaterial.toLowerCase();

  // Explicit facade material wins — this is what Claude recommended to match neighbors
  // Glass as a full cladding only makes sense for steel-frame curtain wall buildings
  if (mat.includes('glass') && structuralSystem !== 'steel') {
    // Ignore — fall through to structural system default (wood → stucco, concrete → concrete)
  } else if (mat.includes('glass')) {
    return { texName: 'steel', roughness: 0.25, metalness: 0.7 }; // curtain wall = steel panels + glass
  }
  if (mat.includes('brick'))                                   return { texName: 'brick',       roughness: 0.92, metalness: 0.0  };
  if (mat.includes('marble'))                                  return { texName: 'marble',      roughness: 0.25, metalness: 0.05 };
  if (mat.includes('stone'))                                   return { texName: 'stone',       roughness: 0.95, metalness: 0.0  };
  // Exterior wood cladding → horizontal siding boards (not interior floor planks)
  if (mat.includes('fiber_cement') || mat.includes('cement'))  return { texName: 'stucco',      roughness: 0.88, metalness: 0.0  };
  if (mat.includes('wood') || mat.includes('timber'))          return { texName: 'wood_siding', roughness: 0.82, metalness: 0.0  };
  if (mat.includes('stucco') || mat.includes('plaster'))       return { texName: 'stucco',      roughness: 0.90, metalness: 0.0  };
  if (mat.includes('concrete'))                                return { texName: 'concrete',    roughness: 0.88, metalness: 0.0  };
  if (mat.includes('steel') || mat.includes('metal'))          return { texName: 'steel',       roughness: 0.35, metalness: 0.55 };

  // Fall back to structural system
  if (structuralSystem === 'steel')    return { texName: 'steel',    roughness: 0.35, metalness: 0.55 };
  if (structuralSystem === 'concrete') return { texName: 'concrete', roughness: 0.88, metalness: 0.0  };

  // Default California wood-frame → stucco
  return { texName: 'stucco', roughness: 0.90, metalness: 0.0 };
}

/** Dispose all cached textures (call on unmount if needed). */
export function disposeTextures() {
  _cache.forEach(t => t.dispose());
  _cache.clear();
}
