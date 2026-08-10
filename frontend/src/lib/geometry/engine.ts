/**
 * Semantic Geometry Engine
 * Converts SemanticBuildingModel → Three.js objects.
 * - Walls are thick solids (not planes)
 * - Openings are real CSG subtractions through walls
 * - PBR materials keyed to semantic material names
 * - HDRI environment handled by the viewer (not here)
 */
import * as THREE from 'three'
import {
  SemanticBuildingModel, SemanticWall, SemanticOpening,
  SemanticPorch, WallMaterial, RoofMaterial,
} from './types'

// ── PBR-ready material colors & roughness ────────────────────────────────────
const WALL_COLORS: Record<WallMaterial | string, { color: string; roughness: number; metalness: number }> = {
  wood_siding:    { color: '#8b6914', roughness: 0.85, metalness: 0.0 },
  brick:          { color: '#a0522d', roughness: 0.90, metalness: 0.0 },
  stucco:         { color: '#d4c5a9', roughness: 0.92, metalness: 0.0 },
  concrete:       { color: '#9a9a9a', roughness: 0.80, metalness: 0.05 },
  stone:          { color: '#7a6a5a', roughness: 0.95, metalness: 0.0 },
  fiber_cement:   { color: '#c0b8aa', roughness: 0.88, metalness: 0.0 },
  metal_panel:    { color: '#708090', roughness: 0.30, metalness: 0.85 },
  glass_curtain:  { color: '#aec8d8', roughness: 0.05, metalness: 0.10 },
}

const ROOF_COLORS: Record<RoofMaterial | string, { color: string; roughness: number }> = {
  asphalt_shingle:       { color: '#3a3530', roughness: 0.95 },
  slate:                 { color: '#4a4855', roughness: 0.90 },
  metal_standing_seam:   { color: '#607080', roughness: 0.30 },
  clay_tile:             { color: '#b5490a', roughness: 0.88 },
  flat_membrane:         { color: '#555555', roughness: 0.70 },
}

function wallMat(material: WallMaterial | string): THREE.MeshStandardMaterial {
  const def = WALL_COLORS[material] ?? WALL_COLORS.stucco
  return new THREE.MeshStandardMaterial({
    color: new THREE.Color(def.color),
    roughness: def.roughness,
    metalness: def.metalness,
    side: THREE.FrontSide,
  })
}

function roofMat(material: RoofMaterial | string): THREE.MeshStandardMaterial {
  const def = ROOF_COLORS[material] ?? ROOF_COLORS.asphalt_shingle
  return new THREE.MeshStandardMaterial({
    color: new THREE.Color(def.color),
    roughness: def.roughness,
    metalness: 0.0,
  })
}

function glassMat(): THREE.MeshStandardMaterial {
  return new THREE.MeshStandardMaterial({
    color: new THREE.Color('#7dd3fc'),
    roughness: 0.05,
    metalness: 0.10,
    transparent: true,
    opacity: 0.55,
    side: THREE.DoubleSide,
  })
}

// ── Utility ──────────────────────────────────────────────────────────────────

function darken(hex: string, factor: number): string {
  const h = hex.replace('#', '')
  const r = Math.floor(parseInt(h.slice(0,2), 16) * factor)
  const g = Math.floor(parseInt(h.slice(2,4), 16) * factor)
  const b = Math.floor(parseInt(h.slice(4,6), 16) * factor)
  return `#${r.toString(16).padStart(2,'0')}${g.toString(16).padStart(2,'0')}${b.toString(16).padStart(2,'0')}`
}

/** Wall direction unit vector (XZ plane) */
function wallDir(wall: SemanticWall): THREE.Vector3 {
  const dx = wall.end[0] - wall.start[0]
  const dz = wall.end[1] - wall.start[1]
  const len = Math.sqrt(dx * dx + dz * dz)
  return new THREE.Vector3(dx / len, 0, dz / len)
}

function wallLength(wall: SemanticWall): number {
  const dx = wall.end[0] - wall.start[0]
  const dz = wall.end[1] - wall.start[1]
  return Math.sqrt(dx * dx + dz * dz)
}

/** Mid-point of wall segment at given floor base */
function wallCenter(wall: SemanticWall, floorY: number): THREE.Vector3 {
  return new THREE.Vector3(
    (wall.start[0] + wall.end[0]) / 2,
    floorY + wall.height_m / 2,
    (wall.start[1] + wall.end[1]) / 2,
  )
}

// ── Wall + opening geometry (CSG or manual vertex punching) ──────────────────

function buildWallWithOpenings(
  wall: SemanticWall,
  openings: SemanticOpening[],
  floorY: number,
  frameColor: string,
  group: THREE.Group,
) {
  const len    = wallLength(wall)
  const dir    = wallDir(wall)
  const t      = wall.thickness_m
  const h      = wall.height_m
  const mat    = wallMat(wall.material)

  // Try CSG via three-bvh-csg — gracefully fall back to manual if unavailable
  try {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const { Brush, Evaluator, SUBTRACTION } = require('three-bvh-csg')

    // Wall solid
    const wallGeo = new THREE.BoxGeometry(len, h, t)
    const wallBrush = new Brush(wallGeo, mat)
    wallBrush.position.set(
      (wall.start[0] + wall.end[0]) / 2,
      floorY + h / 2,
      (wall.start[1] + wall.end[1]) / 2,
    )

    // Rotate brush to align with wall direction
    const angle = Math.atan2(dir.z, dir.x)
    wallBrush.rotation.y = -angle
    wallBrush.updateMatrixWorld()

    const evaluator = new Evaluator()
    let result: any = wallBrush

    for (const op of openings) {
      const ow = op.width_m
      const oh = op.height_m
      // Opening box slightly thicker than wall to ensure clean subtraction
      const opGeo  = new THREE.BoxGeometry(ow, oh, t + 0.05)
      const opMat  = new THREE.MeshStandardMaterial()
      const opBrush = new Brush(opGeo, opMat)

      // Position opening along wall in wall-local space, then rotate
      const localX = -len / 2 + op.offset_m + ow / 2
      const worldPos = new THREE.Vector3(
        wall.start[0] + dir.x * (op.offset_m + ow / 2),
        floorY + op.sill_m + oh / 2,
        wall.start[1] + dir.z * (op.offset_m + ow / 2),
      )
      opBrush.position.copy(worldPos)
      opBrush.rotation.y = -angle
      opBrush.updateMatrixWorld()

      result = evaluator.evaluate(result, opBrush, SUBTRACTION)
    }

    result.castShadow    = true
    result.receiveShadow = true
    group.add(result)

  } catch {
    // CSG unavailable — build wall as solid box with window frames overlaid
    buildWallFallback(wall, openings, floorY, mat, group)
  }

  // Add window glass + frames on top of (or inside) the wall
  for (const op of openings) {
    if (op.type === 'window' || op.type === 'picture_window' || op.type === 'slider') {
      addWindowGlass(wall, op, dir, floorY, frameColor, group)
    } else if (op.type === 'door') {
      addDoor(wall, op, dir, floorY, frameColor, group)
    }
  }
}

/** Fallback: wall as a box, window as a flush quad (no real opening) */
function buildWallFallback(
  wall: SemanticWall,
  openings: SemanticOpening[],
  floorY: number,
  mat: THREE.MeshStandardMaterial,
  group: THREE.Group,
) {
  const len = wallLength(wall)
  const dir = wallDir(wall)
  const angle = Math.atan2(dir.z, dir.x)

  const geo  = new THREE.BoxGeometry(len, wall.height_m, wall.thickness_m)
  const mesh = new THREE.Mesh(geo, mat)
  mesh.position.set(
    (wall.start[0] + wall.end[0]) / 2,
    floorY + wall.height_m / 2,
    (wall.start[1] + wall.end[1]) / 2,
  )
  mesh.rotation.y = -angle
  mesh.castShadow    = true
  mesh.receiveShadow = true
  group.add(mesh)
}

function addWindowGlass(
  wall: SemanticWall,
  op: SemanticOpening,
  dir: THREE.Vector3,
  floorY: number,
  frameColor: string,
  group: THREE.Group,
) {
  const angle = Math.atan2(dir.z, dir.x)
  const cx = wall.start[0] + dir.x * (op.offset_m + op.width_m / 2)
  const cz = wall.start[1] + dir.z * (op.offset_m + op.width_m / 2)
  const cy = floorY + op.sill_m + op.height_m / 2

  // Glass
  const glassGeo  = new THREE.PlaneGeometry(op.width_m - 0.06, op.height_m - 0.06)
  const glassMesh = new THREE.Mesh(glassGeo, glassMat())
  glassMesh.position.set(cx, cy, cz)
  glassMesh.rotation.y = Math.PI / 2 - angle
  group.add(glassMesh)

  // Frame
  const ft = 0.05
  const frameMat = new THREE.MeshStandardMaterial({
    color: new THREE.Color(frameColor),
    roughness: 0.6,
    metalness: 0.0,
  })

  const frameGeo  = new THREE.BoxGeometry(op.width_m + ft*2, op.height_m + ft*2, ft)
  const frameMesh = new THREE.Mesh(frameGeo, frameMat)
  frameMesh.position.set(cx, cy, cz)
  frameMesh.rotation.y = Math.PI / 2 - angle
  frameMesh.castShadow = true
  group.add(frameMesh)

  // Glass pane on top (slightly in front of frame)
  const paneGeo  = new THREE.BoxGeometry(op.width_m - ft, op.height_m - ft, 0.02)
  const paneMesh = new THREE.Mesh(paneGeo, glassMat())
  paneMesh.position.set(cx, cy, cz)
  paneMesh.rotation.y = Math.PI / 2 - angle
  group.add(paneMesh)
}

function addDoor(
  wall: SemanticWall,
  op: SemanticOpening,
  dir: THREE.Vector3,
  floorY: number,
  frameColor: string,
  group: THREE.Group,
) {
  const angle = Math.atan2(dir.z, dir.x)
  const cx = wall.start[0] + dir.x * (op.offset_m + op.width_m / 2)
  const cz = wall.start[1] + dir.z * (op.offset_m + op.width_m / 2)
  const cy = floorY + op.height_m / 2

  const doorMat = new THREE.MeshStandardMaterial({ color: '#7c5c3a', roughness: 0.7 })
  const doorGeo = new THREE.BoxGeometry(op.width_m, op.height_m, 0.06)
  const door    = new THREE.Mesh(doorGeo, doorMat)
  door.position.set(cx, cy, cz)
  door.rotation.y = Math.PI / 2 - angle
  door.castShadow = true
  group.add(door)

  // Door frame
  const ft = 0.07
  const frameMat = new THREE.MeshStandardMaterial({ color: frameColor, roughness: 0.6 })
  const frameGeo = new THREE.BoxGeometry(op.width_m + ft*2, op.height_m + ft, ft)
  const frame    = new THREE.Mesh(frameGeo, frameMat)
  frame.position.set(cx, cy, cz)
  frame.rotation.y = Math.PI / 2 - angle
  group.add(frame)
}

// ── Roof ─────────────────────────────────────────────────────────────────────

function buildRoof(model: SemanticBuildingModel, totalHeight: number, group: THREE.Group) {
  const { roof, footprint, materials } = model
  const mat  = roofMat(roof.material)
  const w    = footprint.width_m
  const d    = footprint.depth_m
  const ox   = footprint.offset_x ?? 0
  const oz   = footprint.offset_z ?? 0
  const ridgeH = (Math.min(w, d) / 2) * (roof.pitch_12 / 12)
  const ov   = roof.overhang_m
  const baseY = totalHeight

  if (roof.type === 'flat') {
    // Flat roof slab
    const geo  = new THREE.BoxGeometry(w + ov*2, 0.25, d + ov*2)
    const mesh = new THREE.Mesh(geo, mat)
    mesh.position.set(ox + w/2, baseY + 0.125, oz + d/2)
    mesh.castShadow    = true
    mesh.receiveShadow = true
    group.add(mesh)

    // Parapet
    const parH = roof.parapet_height_m ?? 0.6
    const parT = 0.18
    const parMat = wallMat(model.materials.wall_body)
    ;[[ox, oz, w, parT], [ox, oz + d - parT, w, parT],
      [ox, oz, parT, d], [ox + w - parT, oz, parT, d]].forEach(([px, pz, pw, pd]) => {
      const g = new THREE.BoxGeometry(pw as number, parH, pd as number)
      const m = new THREE.Mesh(g, parMat)
      m.position.set((px as number) + (pw as number)/2, baseY + parH/2, (pz as number) + (pd as number)/2)
      m.castShadow = true
      group.add(m)
    })
    return
  }

  if (roof.type === 'gabled' || roof.type === 'shed') {
    const verts: number[] = []
    const indices: number[] = []

    const x0 = ox - ov, x1 = ox + w + ov
    const z0 = oz - ov, z1 = oz + d + ov
    const cx  = ox + w / 2

    // Front slope
    verts.push(x0, baseY, z0,  x1, baseY, z0,  cx, baseY + ridgeH, z0 + d/2 + ov)
    indices.push(0,1,2, 2,1,0)
    // Back slope
    verts.push(x0, baseY, z1,  x1, baseY, z1,  cx, baseY + ridgeH, z1 - d/2 - ov)
    indices.push(3,5,4, 4,5,3)
    // Left gable
    verts.push(x0, baseY, z0,  x0, baseY, z1,  cx, baseY + ridgeH, oz + d/2)
    indices.push(6,7,8, 8,7,6)
    // Right gable
    verts.push(x1, baseY, z0,  x1, baseY, z1,  cx, baseY + ridgeH, oz + d/2)
    indices.push(9,11,10, 10,11,9)

    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3))
    geo.setIndex(indices)
    geo.computeVertexNormals()
    const mesh = new THREE.Mesh(geo, mat)
    mesh.castShadow    = true
    mesh.receiveShadow = true
    group.add(mesh)
  }

  if (roof.type === 'hipped') {
    const verts: number[] = []
    const indices: number[] = []
    const x0 = ox - ov, x1 = ox + w + ov
    const z0 = oz - ov, z1 = oz + d + ov
    const inset = Math.min(w, d) * 0.18
    const rx0 = ox + inset, rx1 = ox + w - inset
    const rcz = oz + d / 2
    const ry = baseY + ridgeH

    // Front slope
    verts.push(x0,baseY,z0, x1,baseY,z0, rx1,ry,rcz, rx0,ry,rcz)
    indices.push(0,1,2, 0,2,3, 2,1,0, 3,2,0)
    // Back slope
    verts.push(x0,baseY,z1, x1,baseY,z1, rx1,ry,rcz, rx0,ry,rcz)
    indices.push(4,6,5, 4,7,6, 5,6,4, 6,7,4)
    // Left hip
    verts.push(x0,baseY,z0, x0,baseY,z1, rx0,ry,rcz)
    indices.push(8,9,10, 10,9,8)
    // Right hip
    verts.push(x1,baseY,z0, x1,baseY,z1, rx1,ry,rcz)
    indices.push(11,13,12, 12,13,11)

    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3))
    geo.setIndex(indices)
    geo.computeVertexNormals()
    const mesh = new THREE.Mesh(geo, mat)
    mesh.castShadow = true
    group.add(mesh)
  }
}

// ── Trim bands ───────────────────────────────────────────────────────────────

function buildTrimBands(model: SemanticBuildingModel, group: THREE.Group) {
  const { trim, walls, floors } = model
  if (!trim || trim.band_height_m <= 0) return

  const bandMat = new THREE.MeshStandardMaterial({
    color: new THREE.Color(trim.trim_color),
    roughness: 0.5,
    metalness: 0.0,
  })

  const floorYs = floors.reduce<Record<number, number>>((acc, f) => {
    acc[f.level] = f.level === 0 ? 0 : floors.slice(0, f.level).reduce((s, ff) => s + ff.height_m, 0)
    return acc
  }, {})

  for (const wall of walls) {
    if (!wall.exterior) continue
    const floorY = floorYs[wall.floor] ?? 0

    if (!trim.band_at_floor.includes(wall.floor)) continue

    const len   = wallLength(wall)
    const dir   = wallDir(wall)
    const angle = Math.atan2(dir.z, dir.x)
    const bh    = trim.band_height_m
    const t     = wall.thickness_m + 0.04

    const geo  = new THREE.BoxGeometry(len, bh, t)
    const mesh = new THREE.Mesh(geo, bandMat)
    mesh.position.set(
      (wall.start[0] + wall.end[0]) / 2,
      floorY + wall.height_m - bh / 2,
      (wall.start[1] + wall.end[1]) / 2,
    )
    mesh.rotation.y = -angle
    mesh.castShadow = true
    group.add(mesh)
  }
}

// ── Porches / decks ──────────────────────────────────────────────────────────

function buildPorches(model: SemanticBuildingModel, group: THREE.Group) {
  const { porches, walls, floors } = model
  if (!porches?.length) return

  const floorYs = floors.reduce<Record<number, number>>((acc, f) => {
    acc[f.level] = f.level === 0 ? 0 : floors.slice(0, f.level).reduce((s, ff) => s + ff.height_m, 0)
    return acc
  }, {})

  const deckMat = new THREE.MeshStandardMaterial({ color: '#8b7355', roughness: 0.85 })
  const railMat = new THREE.MeshStandardMaterial({ color: '#5c4a30', roughness: 0.7 })

  for (const porch of porches) {
    const wall  = walls.find(w => w.id === porch.wall_id)
    if (!wall) continue
    const floorY = floorYs[porch.floor] ?? 0
    const dir    = wallDir(wall)
    const angle  = Math.atan2(dir.z, dir.x)

    const mid = new THREE.Vector3(
      (wall.start[0] + wall.end[0]) / 2,
      floorY,
      (wall.start[1] + wall.end[1]) / 2,
    )

    // Porch slab
    const geo  = new THREE.BoxGeometry(porch.width_m, 0.20, porch.depth_m)
    const mesh = new THREE.Mesh(geo, deckMat)
    // Outward normal
    const nx = Math.sin(angle), nz = -Math.cos(angle)
    mesh.position.set(
      mid.x + nx * porch.depth_m / 2,
      floorY + 0.10,
      mid.z + nz * porch.depth_m / 2,
    )
    mesh.rotation.y = -angle
    mesh.receiveShadow = true
    mesh.castShadow    = true
    group.add(mesh)

    // Rail if elevated
    if (porch.floor > 0) {
      const railGeo  = new THREE.BoxGeometry(porch.width_m, 0.9, 0.06)
      const railMesh = new THREE.Mesh(railGeo, railMat)
      railMesh.position.set(
        mid.x + nx * porch.depth_m,
        floorY + 0.55,
        mid.z + nz * porch.depth_m,
      )
      railMesh.rotation.y = -angle
      group.add(railMesh)
    }
  }
}

// ── Main entry point ─────────────────────────────────────────────────────────

export function buildSemanticGeometry(model: SemanticBuildingModel): THREE.Group {
  const group = new THREE.Group()
  group.name  = 'semantic_building'

  const { walls, openings, floors, materials, trim } = model
  const frameColor = materials?.window_frame_color ?? '#3a2a1a'

  // Accumulate floor Y positions
  const floorYs: Record<number, number> = {}
  let cumY = 0
  for (const f of floors) {
    floorYs[f.level] = cumY
    cumY += f.height_m
  }
  const totalHeight = cumY

  // Ground plane
  const fp = model.footprint
  const groundGeo  = new THREE.BoxGeometry(fp.width_m + 0.01, 0.05, fp.depth_m + 0.01)
  const groundMesh = new THREE.Mesh(
    groundGeo,
    new THREE.MeshStandardMaterial({ color: '#2a2a2a', roughness: 1.0 }),
  )
  groundMesh.position.set(
    (fp.offset_x ?? 0) + fp.width_m / 2,
    -0.025,
    (fp.offset_z ?? 0) + fp.depth_m / 2,
  )
  groundMesh.receiveShadow = true
  group.add(groundMesh)

  // Build each wall with its openings
  for (const wall of walls) {
    const floorY     = floorYs[wall.floor] ?? 0
    const wallOpenings = openings.filter(o => o.wall_id === wall.id)
    buildWallWithOpenings(wall, wallOpenings, floorY, frameColor, group)
  }

  // Trim bands
  buildTrimBands(model, group)

  // Porches / decks
  buildPorches(model, group)

  // Roof
  buildRoof(model, totalHeight, group)

  // Center the whole building at origin
  const box = new THREE.Box3().setFromObject(group)
  const center = box.getCenter(new THREE.Vector3())
  group.position.set(-center.x, 0, -center.z)

  return group
}
