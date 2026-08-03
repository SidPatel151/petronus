import { create } from 'zustand';
import api from './api';

export type LayerKey = 'architecture' | 'floors' | 'structure' | 'roof' | 'plumbing' | 'electrical' | 'hvac' | 'fire' | 'fixtures' | 'issues' | 'neighbors' | 'power_grid';

export interface SiteMarker { lat: number; lon: number; address?: string; }
export interface BuildingModel {
  project_id: string; levels: any[]; massing_options: any[];
  chosen_massing_index: number; rooms: any[]; walls: any[];
  columns: any[]; mep_elements: any[]; meshes: any[]; structural_members?: any[];
  issues: any[]; site_context: any; generation_log: string[];
  neighbor_style?: any; spec?: any;
}

interface AppState {
  selectedSite: SiteMarker | null;
  siteContext: any | null;
  infrastructure: any | null;
  neighborConstraints: any | null;
  feasibilityData: any | null;
  clickedBuilding: any | null;
  drawnParcel: any | null;  // GeoJSON Polygon drawn by user — overrides OSM parcel
  chatMessages: { role: 'user' | 'assistant'; content: string }[];
  spec: Partial<any>;
  jobId: string | null;
  jobStatus: string;
  jobProgress: number;
  jobStep: string;
  buildingModel: BuildingModel | null;
  generationSpec: any | null;
  activeLayers: Record<LayerKey, boolean>;
  selectedMassing: number;
  selectedIssueId: string | null;
  setSelectedSite: (site: SiteMarker | null) => void;
  setSiteContext: (ctx: any) => void;
  setInfrastructure: (data: any) => void;
  setNeighborConstraints: (data: any) => void;
  setFeasibilityData: (data: any) => void;
  setClickedBuilding: (b: any | null) => void;
  setDrawnParcel: (p: any | null) => void;
  addChatMessage: (msg: { role: 'user' | 'assistant'; content: string }) => void;
  updateSpec: (partial: Partial<any>) => void;
  setJobId: (id: string | null) => void;
  setJobStatus: (s: string, p: number, step: string) => void;
  setBuildingModel: (m: BuildingModel | null) => void;
  generateBuilding: (generationSpec: any, massingChoice?: number) => Promise<BuildingModel>;
  toggleLayer: (layer: LayerKey) => void;
  setSelectedMassing: (idx: number) => void;
  setSelectedIssue: (id: string | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
  selectedSite: null, siteContext: null, infrastructure: null, neighborConstraints: null, feasibilityData: null,
  clickedBuilding: null, drawnParcel: null, chatMessages: [],
  spec: { stories: 2, floor_to_floor_height_ft: 10, structural_system: 'wood', hvac_preference: 'mini_split', parking_strategy: 'ignore', priority: 'cost' },
  jobId: null, jobStatus: 'idle', jobProgress: 0, jobStep: '', buildingModel: null, generationSpec: null,
  activeLayers: { architecture: true, floors: true, structure: false, roof: true, plumbing: true, electrical: true, hvac: true, fire: true, fixtures: true, issues: true, neighbors: true, power_grid: true },
  selectedMassing: 0, selectedIssueId: null,
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
