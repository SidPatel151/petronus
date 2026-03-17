# AutoBIM — Automated Building Design for California

Automated MEP building model generation for California multi-family residential (≤3 stories).
Built with FastAPI + Next.js + Three.js + MapLibre.

---

## What It Does

1. **Click anywhere in California** on the map → fetches real infrastructure data (OSM fire hydrants, pipes, roads, power lines) + FEMA flood zone
2. **Fill in building parameters** (stories, area, systems, priority)
3. **Hit Generate** → backend runs the full pipeline:
   - Site context (parcel, setbacks, flood zone, seismic category)
   - 3 massing options (rectangle, L-shape, bar building)
   - Floorplan layout (corridor, stair core, unit templates)
   - MEP routing (plumbing risers/branches, electrical panels/feeders, HVAC)
   - CA compliance checks (egress, corridor width, flood, seismic bracing)
4. **View in 3D** with layer toggles (Architecture / Structure / Plumbing / Electrical / HVAC / Issues)

---

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+
- Docker (for Postgres + Redis)

### Install
```bash
chmod +x setup.sh run_backend.sh run_frontend.sh
./setup.sh
```

### Run
```bash
# Terminal 1 — infrastructure (Postgres + Redis)
docker-compose up -d

# Terminal 2 — Python API
./run_backend.sh

# Terminal 3 — Next.js frontend
./run_frontend.sh
```

Open **http://localhost:3000**
API docs at **http://localhost:8000/docs**

---

## Free Data Sources Used

| Data | Source | Cost |
|------|--------|------|
| Fire hydrants, pipes, roads | OpenStreetMap Overpass API | Free |
| Parcel / lot polygons | OpenStreetMap | Free |
| Geocoding | Nominatim (OSM) | Free |
| FEMA flood zones | FEMA MSC ArcGIS REST API | Free |
| Map tiles | OpenStreetMap raster tiles | Free |

No API keys required for basic usage.

---

## Project Structure

```
autobim/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app
│   │   ├── core/
│   │   │   ├── config.py        # Settings
│   │   │   └── database.py      # SQLAlchemy setup
│   │   ├── models/
│   │   │   └── schemas.py       # All Pydantic models
│   │   ├── api/
│   │   │   ├── projects.py      # Project CRUD
│   │   │   ├── site.py          # Site context + infrastructure
│   │   │   ├── generate.py      # Generation endpoints
│   │   │   └── exports.py       # IFC/DXF/PDF export stubs
│   │   ├── services/
│   │   │   ├── site_context.py  # OSM + FEMA + USGS data fetching
│   │   │   └── orchestrator.py  # Generation pipeline orchestrator
│   │   └── generators/
│   │       ├── massing.py       # 3 massing options generator
│   │       ├── floorplan.py     # Unit layout + corridor generator
│   │       ├── mep.py           # Plumbing + electrical + HVAC router
│   │       └── compliance.py    # CA rule engine
│   └── requirements.txt
│
├── frontend/
│   └── src/
│       ├── app/
│       │   ├── page.tsx         # Main layout (map + 3D + panels)
│       │   ├── layout.tsx
│       │   └── globals.css
│       ├── components/
│       │   ├── map/
│       │   │   └── SiteMap.tsx  # MapLibre map with OSM infra layers
│       │   ├── viewer/
│       │   │   └── BuildingViewer.tsx  # Three.js 3D viewer
│       │   └── ui/
│       │       ├── ProjectWizard.tsx   # Spec form + generate button
│       │       ├── MassingPicker.tsx   # Choose massing A/B/C
│       │       └── IssuesPanel.tsx     # Compliance issues + log
│       └── lib/
│           ├── store.ts         # Zustand global state
│           └── api.ts           # Axios API client
│
├── docker-compose.yml           # Postgres + Redis
├── setup.sh                     # One-shot install
├── run_backend.sh
└── run_frontend.sh
```

---

## What's Next (after demo)

- [ ] IFC export (ifcopenshell wired up)
- [ ] DXF/DWG export (ezdxf)
- [ ] PDF blueprint generation (reportlab)
- [ ] Full CA code coverage (CBC/CEC/CPC/CMC)
- [ ] Structural layout generator (columns, shear walls, grids)
- [ ] Clash detection engine
- [ ] Permit-ready plan sets
- [ ] Celery job queue for async generation
- [ ] PostgreSQL persistence
