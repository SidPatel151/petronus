import axios from 'axios';

const API = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000',
  timeout: 120000,
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
  createProject: (name: string, spec: any) =>
    API.post('/api/projects/', { name, spec }).then(r => r.data),
  quickGenerate: (spec: any, massingChoice = 0) =>
    API.post('/api/generate/quick', spec, { params: { massing_choice: massingChoice } }).then(r => r.data),
  getJobStatus: (jobId: string) =>
    API.get(`/api/generate/status/${jobId}`).then(r => r.data),
  exportJson: (projectId: string) =>
    API.get(`/api/exports/${projectId}/json`).then(r => r.data),
  getFeasibility: (lat: number, lon: number, parcel_polygon?: any) =>
    API.post('/api/site/feasibility', { lat, lon, parcel_polygon }).then(r => r.data),
  chat: (messages: any[], site_context?: any, building_model?: any, clicked_building?: any) =>
    API.post('/api/chat/', { messages, site_context, building_model, clicked_building }).then(r => r.data),
  saveProject: (name: string, address: string, spec: any, building_model: any) =>
    API.post('/api/projects/save', { name, address, spec, building_model }).then(r => r.data),
  listProjects: () =>
    API.get('/api/projects/').then(r => r.data),
};

export default api;
