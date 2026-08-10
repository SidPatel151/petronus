import axios from 'axios';

export type ConstructionScope = 'new_construction' | 'addition' | 'alteration';
export type CaliforniaCodeCycle = '2022' | '2025';
export type PrimaryDwellingSprinklerRequirement = 'required' | 'not_required' | 'unknown';

export interface ProjectSiteInput {
  address?: string | null;
  latlon?: { lat: number; lon: number } | null;
  parcel_polygon?: Record<string, unknown> | null;
}

export interface ProjectSpec {
  region_country: 'US';
  region_state: 'CA';
  occupancy?: 'SingleFamilyResidential' | 'MultiFamilyResidential' | null;
  construction_scope: ConstructionScope;
  permit_set?: boolean;
  permit_application_date?: string | null;
  code_cycle: CaliforniaCodeCycle;
  jurisdiction_city?: string | null;
  site: ProjectSiteInput;
  building_use?: 'single_family' | 'multi_family' | 'adu';
  bedrooms?: number | null;
  bathrooms?: number | null;
  house_archetype?: string | null;
  target_gross_area_sqft?: number | null;
  unit_count?: number | null;
  stories?: number;
  floor_to_floor_height_ft?: number;
  structural_system?: string;
  hvac_preference?: string;
  parking_strategy?: string;
  priority?: string;
  style?: string | null;
  material_overrides?: Record<string, string> | null;
  fine_details?: Record<string, unknown> | null;
  primary_dwelling_sprinkler_requirement: PrimaryDwellingSprinklerRequirement;
  primary_dwelling_sprinkler_determination_source?: string | null;
  /** @deprecated Compatibility with saved projects only; not a legal determination. */
  primary_dwelling_sprinklered?: boolean | null;
  max_height_ft?: number | null;
  max_floors?: number | null;
  max_bedrooms?: number | null;
  max_sqft?: number | null;
}

export type ProjectSpecDraft = Partial<Omit<ProjectSpec, 'site'>> & {
  site?: ProjectSiteInput;
};

const API = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
  timeout: 120000,
});

// Attach JWT from Zustand persist storage on every request
API.interceptors.request.use((config) => {
  try {
    const raw = localStorage.getItem('petronus-auth');
    if (raw) {
      const parsed = JSON.parse(raw);
      const t = parsed?.state?.token;
      if (t && t !== '__dev_skip__') {
        config.headers = config.headers ?? {};
        (config.headers as any)['Authorization'] = `Bearer ${t}`;
      }
    }
  } catch {}
  return config;
});

export const api = {
  getSiteContext: (lat: number, lon: number, parcel_polygon?: any) =>
    API.post('/api/site/context', { lat, lon, parcel_polygon }).then(r => r.data),
  getInfrastructure: (lat: number, lon: number) =>
    API.post('/api/site/infrastructure', { lat, lon }).then(r => r.data),
  getNeighbors: (lat: number, lon: number, parcel_polygon?: any) =>
    API.post('/api/site/neighbors', { lat, lon, parcel_polygon }).then(r => r.data),
  geocode: (address: string) =>
    API.get('/api/site/geocode', { params: { address } }).then(r => r.data),
  createProject: (name: string, spec: ProjectSpec) =>
    API.post('/api/projects/', { name, spec }).then(r => r.data),
  quickGenerate: (spec: ProjectSpec, massingChoice = 0) =>
    API.post('/api/generate/quick', spec, { params: { massing_choice: massingChoice } }).then(r => r.data),
  getJobStatus: (jobId: string) =>
    API.get(`/api/generate/status/${jobId}`).then(r => r.data),
  exportJson: (projectId: string) =>
    API.get(`/api/exports/${projectId}/json`).then(r => r.data),
  getFeasibility: (lat: number, lon: number, parcel_polygon?: any) =>
    API.post('/api/site/feasibility', { lat, lon, parcel_polygon }).then(r => r.data),
  chat: (messages: any[], site_context?: any, building_model?: any, clicked_building?: any) =>
    API.post('/api/chat/', { messages, site_context, building_model, clicked_building }).then(r => r.data),
  saveProject: (name: string, address: string, spec: ProjectSpec, building_model: any) =>
    API.post('/api/projects/save', { name, address, spec, building_model }).then(r => r.data),
  listProjects: () =>
    API.get('/api/projects/').then(r => r.data),
};

export default api;
