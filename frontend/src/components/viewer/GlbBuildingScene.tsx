'use client';
import { Component, useEffect, useMemo, type ReactNode } from 'react';
import { useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import { useAppStore, LayerKey } from '@/lib/store';

// Must match backend/app/services/render_payload.py's layer vocabulary and the
// object naming convention backend/blender_worker/scene_builder.py uses
// (f"{layer}_{type}_{id}") — "issues"/"neighbors"/"power_grid" don't apply to the
// building GLB itself (they're site-context overlays rendered outside this
// component) so they're intentionally not in this list.
const LAYER_PREFIXES: LayerKey[] = [
  'shell', 'architecture', 'floors', 'structure', 'roof',
  'plumbing', 'electrical', 'hvac', 'fire', 'fixtures',
];

// A data: URI (not a Blob object URL) deliberately — object URLs need explicit
// revocation via useEffect cleanup, and this app runs with reactStrictMode: true
// (next.config.js), which deliberately double-invokes effects in dev (mount →
// effect → cleanup → effect again) to surface exactly this class of bug: the
// cleanup was revoking the blob URL almost immediately after creating it, often
// before useGLTF's async fetch of that same URL had finished, so the model
// silently failed to load with no visible error. A data: URI needs no lifecycle
// management at all, so there's nothing to race.
function toDataUri(b64: string): string {
  return `data:model/gltf-binary;base64,${b64}`;
}

function GlbBuildingSceneInner({ glbBase64 }: { glbBase64: string }) {
  const { activeLayers } = useAppStore();

  const url = useMemo(() => toDataUri(glbBase64), [glbBase64]);

  const { scene } = useGLTF(url);

  // Group every node in the loaded scene by its LayerKey name-prefix once per load.
  const layerGroups = useMemo(() => {
    const groups: Partial<Record<LayerKey, THREE.Object3D[]>> = {};
    scene.traverse((obj) => {
      const prefix = LAYER_PREFIXES.find((p) => obj.name.startsWith(`${p}_`));
      if (prefix) (groups[prefix] ??= []).push(obj);
    });
    return groups;
  }, [scene]);

  // Sync visibility with the same activeLayers store the procedural viewer uses,
  // so the layer-toggle UI keeps working identically against the GLB.
  useEffect(() => {
    for (const [layer, objs] of Object.entries(layerGroups)) {
      const visible = activeLayers[layer as LayerKey] ?? true;
      for (const obj of objs as THREE.Object3D[]) obj.visible = visible;
    }
  }, [layerGroups, activeLayers]);

  // The GLB's outer shell and roof are real solid geometry — from outside they
  // hide every interior wall and room behind them. Fade them so "floors" lets
  // you see the plan inside.
  //
  // Only the 'shell' and 'roof' layers are faded. This used to fade
  // 'architecture', which the backend also used for interior walls, doors,
  // windows and stairs — so the interior went translucent along with the box
  // around it and the plan was never legible at any toggle setting. The shell
  // now has its own layer (render_payload.MESH_LAYER_MAP) precisely so the
  // interior can stay opaque while the exterior turns to glass.
  useEffect(() => {
    const shellObjs = [...(layerGroups.shell ?? []), ...(layerGroups.roof ?? [])];
    const materials = new Set<THREE.Material>();
    for (const obj of shellObjs) {
      const mesh = obj as THREE.Mesh;
      if (!mesh.isMesh || !mesh.material) continue;
      const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      for (const m of mats) materials.add(m);
    }
    const seeThrough = activeLayers.floors ?? true;
    for (const mat of materials) {
      const m = mat as THREE.Material & { opacity: number; side: THREE.Side };
      m.transparent = seeThrough;
      m.opacity = seeThrough ? 0.18 : 1.0;
      m.side = seeThrough ? THREE.DoubleSide : THREE.FrontSide;
      m.needsUpdate = true;
    }
  }, [layerGroups, activeLayers]);

  return <primitive object={scene} castShadow receiveShadow />;
}

// A GLTFLoader parse failure (or any other error inside the loaded scene) would
// otherwise throw inside the Canvas's own React tree with no boundary to catch
// it — silently blanking the whole 3D view rather than just this one piece of
// it. Render nothing rather than take the rest of the scene down with it.
class GlbErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  state = { hasError: false };
  static getDerivedStateFromError() {
    return { hasError: true };
  }
  componentDidCatch(error: unknown) {
    console.error('GlbBuildingScene failed to load:', error);
  }
  render() {
    return this.state.hasError ? null : this.props.children;
  }
}

export default function GlbBuildingScene(props: { glbBase64: string }) {
  return (
    <GlbErrorBoundary>
      <GlbBuildingSceneInner {...props} />
    </GlbErrorBoundary>
  );
}
