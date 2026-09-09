import { create } from 'zustand';
import api, { type ProjectSpec, type ProjectSpecDraft } from './api';

// 'shell' is the opaque outer massing box, kept separate from 'architecture'
// (interior walls, doors, windows) so the viewer can turn the exterior to glass
// without also fading the plan inside it.
export type LayerKey = 'shell' | 'architecture' | 'floors' | 'structure' | 'roof' | 'plumbing' | 'electrical' | 'hvac' | 'fire' | 'fixtures' | 'issues' | 'neighbors' | 'power_grid';

export interface SiteMarker { lat: number; lon: number; address?: string; }
export interface BuildingModel {
  project_id: string; levels: any[]; massing_options: any[];
  chosen_massing_index: number; rooms: any[]; walls: any[];
  columns: any[]; mep_elements: any[]; meshes: any[]; structural_members?: any[];
  issues: any[]; site_context: any; generation_log: string[];
  neighbor_style?: any; spec?: ProjectSpec;
  glb_data?: string | null;
  render_source?: 'blender' | 'fallback';
}

export interface AuthUser { id: string; name: string; email: string; avatar?: string; }

export interface BlueprintWarning {
  id: string; severity: 'warning' | 'info'; type: string;
  message: string; room_ids: string[]; level?: number | null;
}

interface AppState {
  // Auth
  user: AuthUser | null;
  token: string | null;
  setAuth: (user: AuthUser, token: string) => void;
  clearAuth: () => void;

  selectedSite: SiteMarker | null;
  siteContext: any | null;
  infrastructure: any | null;
  neighborConstraints: any | null;
  feasibilityData: any | null;
  clickedBuilding: any | null;
  drawnParcel: any | null;
  chatMessages: { role: 'user' | 'assistant'; content: string }[];
  spec: ProjectSpecDraft;
  jobId: string | null;
  jobStatus: string;
  jobProgress: number;
  jobStep: string;
  buildingModel: BuildingModel | null;
  generationSpec: ProjectSpec | null;
  activeLayers: Record<LayerKey, boolean>;
  selectedMassing: number;
  selectedIssueId: string | null;

  // ── Blueprint (2D floorplan editing stage) ────────────────────────────
  blueprintDraftId: string | null;
  blueprintLevels: any[];
  blueprintRooms: any[];
  blueprintWalls: any[];
  blueprintFootprintEnvelopes: Record<string, number[][]>;
  blueprintWarnings: BlueprintWarning[];
  blueprintTargetSqft: number;
  blueprintMassingOptions: any[];
  blueprintChosenMassingIndex: number;
  blueprintSpec: ProjectSpec | null;
  blueprintActiveFloor: number;
  blueprintSelectedRoomId: string | null;
  blueprintBusy: boolean;
  blueprintError: string;
  blueprintFinalizing: boolean;

  startBlueprintDraft: (spec: ProjectSpec, massingChoice?: number) => Promise<void>;
  applyBlueprintOp: (opType: string, params: Record<string, unknown>) => Promise<{ ok: boolean; error?: string }>;
  setBlueprintActiveFloor: (level: number) => void;
  setBlueprintSelectedRoom: (id: string | null) => void;
  finalizeBlueprint: () => Promise<BuildingModel | null>;
  clearBlueprintDraft: () => void;

  setSelectedSite: (site: SiteMarker | null) => void;
  setSiteContext: (ctx: any) => void;
  setInfrastructure: (data: any) => void;
  setNeighborConstraints: (data: any) => void;
  setFeasibilityData: (data: any) => void;
  setClickedBuilding: (b: any | null) => void;
  setDrawnParcel: (p: any | null) => void;
  addChatMessage: (msg: { role: 'user' | 'assistant'; content: string }) => void;
  updateSpec: (partial: ProjectSpecDraft) => void;
  setJobId: (id: string | null) => void;
  setJobStatus: (s: string, p: number, step: string) => void;
  setBuildingModel: (m: BuildingModel | null) => void;
  generateBuilding: (generationSpec: ProjectSpec, massingChoice?: number) => Promise<BuildingModel>;
  toggleLayer: (layer: LayerKey) => void;
  setSelectedMassing: (idx: number) => void;
  setSelectedIssue: (id: string | null) => void;
}

export const useAppStore = create<AppState>((set, get) => ({
  selectedSite: null, siteContext: null, infrastructure: null, neighborConstraints: null, feasibilityData: null,
  clickedBuilding: null, drawnParcel: null, chatMessages: [],
  spec: {
    construction_scope: 'new_construction',
    permit_application_date: null,
    code_cycle: '2025',
    primary_dwelling_sprinkler_requirement: 'unknown',
    primary_dwelling_sprinkler_determination_source: null,
    stories: 2,
    floor_to_floor_height_ft: 10,
    structural_system: 'wood',
    hvac_preference: 'mini_split',
    parking_strategy: 'ignore',
    priority: 'cost',
  },
  jobId: null, jobStatus: 'idle', jobProgress: 0, jobStep: '', buildingModel: null, generationSpec: null,
  activeLayers: { shell: true, architecture: true, floors: true, structure: false, roof: true, plumbing: true, electrical: true, hvac: true, fire: true, fixtures: true, issues: true, neighbors: true, power_grid: true },
  selectedMassing: 0, selectedIssueId: null,

  blueprintDraftId: null, blueprintLevels: [], blueprintRooms: [], blueprintWalls: [],
  blueprintFootprintEnvelopes: {}, blueprintWarnings: [], blueprintTargetSqft: 0,
  blueprintMassingOptions: [], blueprintChosenMassingIndex: 0, blueprintSpec: null,
  blueprintActiveFloor: 0, blueprintSelectedRoomId: null, blueprintBusy: false,
  blueprintError: '', blueprintFinalizing: false,

  startBlueprintDraft: async (spec, massingChoice = 0) => {
    set({ blueprintBusy: true, blueprintError: '' });
    try {
      const d = await api.blueprintDraft(spec, massingChoice);
      set({
        blueprintDraftId: d.draft_id,
        blueprintLevels: d.levels,
        blueprintRooms: d.rooms,
        blueprintWalls: d.walls,
        blueprintFootprintEnvelopes: d.footprint_envelopes,
        blueprintWarnings: d.warnings,
        blueprintTargetSqft: d.target_sqft,
        blueprintMassingOptions: d.massing_options,
        blueprintChosenMassingIndex: d.chosen_massing_index,
        blueprintSpec: d.spec,
        blueprintActiveFloor: 0,
        blueprintSelectedRoomId: null,
        blueprintBusy: false,
      });
    } catch (e: any) {
      const detail = e.response?.data?.detail;
      const msg = Array.isArray(detail)
        ? detail.map((item: any) => `${item.loc?.join('.')}: ${item.msg}`).join(' | ')
        : detail || e.message || 'Failed to draft floorplan';
      set({ blueprintBusy: false, blueprintError: msg });
      throw e;
    }
  },

  applyBlueprintOp: async (opType, params) => {
    const draftId = get().blueprintDraftId;
    if (!draftId) return { ok: false, error: 'No active blueprint draft' };
    set({ blueprintBusy: true });
    try {
      const res = await api.blueprintEdit(draftId, { op_type: opType, params });
      set({
        blueprintRooms: res.rooms,
        blueprintWalls: res.walls,
        blueprintWarnings: res.warnings,
        blueprintBusy: false,
      });
      return { ok: res.ok, error: res.error };
    } catch (e: any) {
      // Drafts live in the backend's memory (like its job store), so a server
      // restart drops them. Say that plainly instead of surfacing a bare
      // "Draft not found", and clear the stale draft so the UI isn't stuck
      // on a blueprint the server no longer knows about.
      if (e.response?.status === 404) {
        set({
          blueprintBusy: false,
          blueprintDraftId: null,
          blueprintError: 'This blueprint expired because the server restarted. Generate a new one from Project Setup.',
        });
        return { ok: false, error: 'Blueprint expired — the server restarted. Generate a new one from Project Setup.' };
      }
      const detail = e.response?.data?.detail;
      const msg = Array.isArray(detail)
        ? detail.map((item: any) => `${item.loc?.join('.')}: ${item.msg}`).join(' | ')
        : detail || e.message || 'Edit failed';
      set({ blueprintBusy: false });
      return { ok: false, error: msg };
    }
  },

  setBlueprintActiveFloor: (level) => set({ blueprintActiveFloor: level, blueprintSelectedRoomId: null }),
  setBlueprintSelectedRoom: (id) => set({ blueprintSelectedRoomId: id }),

  finalizeBlueprint: async () => {
    const draftId = get().blueprintDraftId;
    if (!draftId) return null;
    set({ blueprintFinalizing: true, jobStatus: 'running', jobProgress: 0, jobStep: 'Finalizing blueprint' });
    try {
      const job = await api.blueprintFinalize(draftId);
      const jobId = job.job_id;
      set({ jobId });

      // No polling infrastructure exists elsewhere in the app yet — /finalize
      // is a background job (Blender render can take a while), so poll it here.
      const POLL_MS = 2000;
      const MAX_ATTEMPTS = 240; // 8 minutes
      for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
        const status = await api.getJobStatus(jobId);
        set({ jobStatus: status.status, jobProgress: status.progress, jobStep: status.current_step });
        if (status.status === 'done') {
          const model = status.result as BuildingModel;
          set({
            buildingModel: model,
            generationSpec: model?.spec ?? get().blueprintSpec ?? null,
            selectedMassing: model?.chosen_massing_index ?? get().blueprintChosenMassingIndex,
            blueprintFinalizing: false,
            blueprintDraftId: null,
          });
          return model;
        }
        if (status.status === 'failed') {
          set({ blueprintFinalizing: false, blueprintError: status.error || 'Finalize failed', jobStatus: 'failed' });
          throw new Error(status.error || 'Finalize failed');
        }
        await new Promise((r) => setTimeout(r, POLL_MS));
      }
      set({ blueprintFinalizing: false, blueprintError: 'Finalize timed out', jobStatus: 'failed' });
      throw new Error('Finalize timed out');
    } catch (e: any) {
      set({ blueprintFinalizing: false });
      throw e;
    }
  },

  clearBlueprintDraft: () => set({
    blueprintDraftId: null, blueprintLevels: [], blueprintRooms: [], blueprintWalls: [],
    blueprintFootprintEnvelopes: {}, blueprintWarnings: [], blueprintTargetSqft: 0,
    blueprintMassingOptions: [], blueprintChosenMassingIndex: 0, blueprintSpec: null,
    blueprintActiveFloor: 0, blueprintSelectedRoomId: null, blueprintError: '',
  }),

  setSelectedSite: (site) => set({ selectedSite: site }),
  setSiteContext: (ctx) => set({ siteContext: ctx }),
  setInfrastructure: (data) => set({ infrastructure: data }),
  setNeighborConstraints: (data) => set({ neighborConstraints: data }),
  setFeasibilityData: (data) => set({ feasibilityData: data }),
  setClickedBuilding: (b) => set({ clickedBuilding: b }),
  setDrawnParcel: (p) => set({ drawnParcel: p }),
  addChatMessage: (msg) => set((s) => ({ chatMessages: [...s.chatMessages, msg] })),
  updateSpec: (partial) => set((s) => ({ spec: { ...s.spec, ...partial } })),
  setJobId: (id) => set({ jobId: id }),
  setJobStatus: (jobStatus, jobProgress, jobStep) => set({ jobStatus, jobProgress, jobStep }),
  setBuildingModel: (m) => set({
    buildingModel: m,
    generationSpec: m?.spec ?? null,
    selectedMassing: m?.chosen_massing_index ?? 0,
  }),
  generateBuilding: async (generationSpec, massingChoice = 0) => {
    if (!Number.isInteger(massingChoice) || massingChoice < 0 || massingChoice > 2) {
      throw new Error('Massing choice must be option A, B, or C.');
    }

    set({
      jobStatus: 'running',
      jobProgress: 0,
      jobStep: massingChoice === 0 ? 'Generating building' : `Regenerating massing option ${String.fromCharCode(65 + massingChoice)}`,
    });

    try {
      const response = await api.quickGenerate(generationSpec, massingChoice);
      const model = response?.result as BuildingModel | undefined;
      if (!model) {
        throw new Error(response?.error || 'Generation did not return a building model.');
      }

      const committedChoice = model.chosen_massing_index ?? massingChoice;
      set({
        buildingModel: model,
        generationSpec: model.spec ?? generationSpec,
        selectedMassing: committedChoice,
        jobStatus: 'done',
        jobProgress: 100,
        jobStep: 'Done',
      });
      return model;
    } catch (error) {
      set({ jobStatus: 'failed', jobProgress: 0, jobStep: 'Generation failed' });
      throw error;
    }
  },
  toggleLayer: (layer) => set((s) => ({ activeLayers: { ...s.activeLayers, [layer]: !s.activeLayers[layer] } })),
  setSelectedMassing: (idx) => set({ selectedMassing: idx }),
  setSelectedIssue: (id) => set({ selectedIssueId: id }),
}));
