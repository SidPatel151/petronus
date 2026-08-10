'use client'
/**
 * SemanticViewer — renders buildings from Claude's parametric model.
 * - Real thick walls built from SemanticBuildingModel
 * - CSG wall openings (windows cut through, not painted on)
 * - PBR materials per wall material type
 * - HDRI environment lighting (Revit-like realism)
 * - Orbit + zoom navigation
 */
import React, { useEffect, useRef, useMemo } from 'react'
import { Canvas, useThree } from '@react-three/fiber'
import { OrbitControls, Environment, ContactShadows, Grid, Html } from '@react-three/drei'
import * as THREE from 'three'
import { buildSemanticGeometry } from '@/lib/geometry/engine'
import { SemanticBuildingModel } from '@/lib/geometry/types'

// ── Building mesh — renders one semantic model ────────────────────────────────

function SemanticBuilding({ model }: { model: SemanticBuildingModel }) {
  const groupRef = useRef<THREE.Group>(null)

  const geometry = useMemo(() => {
    try {
      return buildSemanticGeometry(model)
    } catch (e) {
      console.error('Semantic geometry error:', e)
      return null
    }
  }, [model])

  useEffect(() => {
    if (!groupRef.current || !geometry) return
    // Clear old geometry
    while (groupRef.current.children.length > 0) {
      groupRef.current.remove(groupRef.current.children[0])
    }
    groupRef.current.add(geometry)
  }, [geometry])

  return <group ref={groupRef} />
}

// ── Camera setup — auto-fit to building ─────────────────────────────────────

function AutoCamera({ model }: { model: SemanticBuildingModel }) {
  const { camera } = useThree()

  useEffect(() => {
    const w = model.footprint.width_m
    const d = model.footprint.depth_m
    const totalH = model.floors.reduce((s, f) => s + f.height_m, 0)
    const diag = Math.sqrt(w * w + d * d)
    const dist = diag * 1.6 + totalH * 0.5

    camera.position.set(dist * 0.7, totalH * 0.9, dist * 0.9)
    camera.lookAt(0, totalH / 2, 0)
    camera.near = 0.1
    camera.far  = 1000
    camera.updateProjectionMatrix()
  }, [model, camera])

  return null
}

// ── Info overlay ─────────────────────────────────────────────────────────────

function InfoOverlay({ model }: { model: SemanticBuildingModel }) {
  const walls    = model.walls?.length ?? 0
  const openings = model.openings?.length ?? 0
  const source   = (model as any)._source ?? 'claude'
  const intent   = model.style_intent ?? ''

  return (
    <div className="absolute top-3 left-3 z-10 pointer-events-none">
      <div className="bg-black/60 backdrop-blur-sm rounded-lg px-3 py-2 text-white text-xs font-mono space-y-0.5 max-w-xs">
        <div className="text-[var(--accent)] font-semibold truncate">{intent}</div>
        <div className="text-white/60">
          {walls} walls · {openings} openings · source: {source}
        </div>
        <div className="text-white/40 text-[10px]">
          {model.footprint.width_m.toFixed(1)}m × {model.footprint.depth_m.toFixed(1)}m · {model.floors.length} floors
        </div>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

interface SemanticViewerProps {
  model: SemanticBuildingModel
  className?: string
}

export default function SemanticViewer({ model, className = '' }: SemanticViewerProps) {
  if (!model) {
    return (
      <div className={`flex items-center justify-center bg-[var(--surface)] rounded-lg ${className}`}>
        <span className="text-[var(--text-secondary)] text-sm font-mono">No parametric model yet</span>
      </div>
    )
  }

  return (
    <div className={`relative ${className}`}>
      <InfoOverlay model={model} />
      <Canvas
        shadows
        camera={{ fov: 45, near: 0.1, far: 1000 }}
        gl={{ antialias: true, toneMapping: THREE.ACESFilmicToneMapping, toneMappingExposure: 1.1 }}
        style={{ background: '#0f1117' }}
      >
        {/* HDRI environment — gives Revit-like PBR reflections and ambient light */}
        <Environment preset="sunset" background={false} />

        {/* Directional sun light with shadows */}
        <directionalLight
          castShadow
          position={[20, 30, 15]}
          intensity={1.8}
          shadow-mapSize-width={2048}
          shadow-mapSize-height={2048}
          shadow-camera-near={0.5}
          shadow-camera-far={200}
          shadow-camera-left={-40}
          shadow-camera-right={40}
          shadow-camera-top={40}
          shadow-camera-bottom={-40}
        />
        <ambientLight intensity={0.35} />

        {/* Ground contact shadow */}
        <ContactShadows
          position={[0, -0.01, 0]}
          opacity={0.5}
          scale={60}
          blur={2.5}
          far={10}
        />

        {/* Ground grid */}
        <Grid
          args={[60, 60]}
          position={[0, -0.02, 0]}
          cellColor="#333"
          sectionColor="#555"
          fadeDistance={50}
          infiniteGrid
        />

        {/* The building */}
        <SemanticBuilding model={model} />

        {/* Auto-fit camera */}
        <AutoCamera model={model} />

        {/* Orbit controls — scroll to zoom, drag to orbit */}
        <OrbitControls
          makeDefault
          enableDamping
          dampingFactor={0.05}
          minDistance={3}
          maxDistance={200}
          maxPolarAngle={Math.PI / 2 - 0.05}
        />
      </Canvas>
    </div>
  )
}
