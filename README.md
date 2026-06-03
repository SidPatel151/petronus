# Petronus — AI-Assisted Residential BIM

Generate a complete 3D building model from a parcel click and a few parameters. Petronus automates the full pipeline: massing → floor plan → facade → MEP routing → California code compliance — all in the browser, no CAD software required.

Built with **FastAPI · Next.js · Three.js · MapLibre · Claude AI**

---

## What It Generates

**Supported building types**
- Single-family residential (SFR) — 1–3 stories
- ADU / accessory dwelling unit
- Multi-family low-rise (≤ 3 stories)
- Victorian narrow-lot
- Custom archetypes via JSON config

**Full pipeline (~5 seconds)**
1. **Site context** — parcel polygon, setbacks, FEMA flood zone, seismic category, neighbor buildings from OSM
2. **AI design brief** — Claude picks facade material, massing shape, window ratio, and balcony depth based on site + neighborhood context
3. **Massing** — 3 scored options (rectangle, L-shape, U-court); Victorian uses narrow-lot rectangle
4. **Floor plan** — BFS room layout, stair core with void, corridor, interior doors, minimum room-width enforcement
5. **Facade** — windows, entry door, porch + columns + railings + canopy (gabled styles), gabled/shed/flat roof with eave overhang
6. **MEP routing** — plumbing stacks, fire risers, HVAC ducts + rooftop units, electrical panels + conduit; routed through wall chases only, never stairwells
7. **Compliance** — CA Building Code, CEC, CMC, CPC, Title 24 energy, IBC structural, seismic (CBC/ASCE 7)

---

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js 18+

### Install & run

```bash
chmod +x setup.sh
./setup.sh

./run_backend.sh     # FastAPI at http://localhost:8000
./run_frontend.sh    # Next.js at http://localhost:3000
```

Copy `backend/.env.example` → `backend/.env` and add your Anthropic API key:

```
ANTHROPIC_API_KEY=sk-ant-...
```

The AI design brief is optional — the system falls back to neighbor-derived defaults if no key is set.

---

## Project Structure

```
petronus/
├── backend/
│   └── app/
│       ├── api/               # FastAPI routes (generate, chat, site)
│       ├── generators/
│       │   ├── massing.py     # 3 massing options + roof + porch geometry
│       │   ├── floorplan.py   # Room layout, stair void, interior walls
│       │   ├── facade.py      # Windows, doors, floor bands
│       │   ├── mep.py         # MEP routing + chase selection
│       │   └── compliance.py  # CA/IBC/seismic rule engine
│       ├── services/
│       │   ├── orchestrator.py      # Full pipeline coordinator
│       │   ├── ai_brief.py          # Claude design brief
│       │   └── archetype_loader.py  # JSON archetype configs
│       ├── data/
│       │   ├── archetypes/          # adu_compact.json, victorian_narrow_lot.json
│       │   └── training/            # Blueprint extraction labels (51 examples)
│       └── ml/
│           └── blueprint_extractor.py   # Claude vision → structured JSON
│
├── frontend/
│   └── src/
│       ├── app/app/page.tsx         # Main layout
│       ├── components/
│       │   ├── map/SiteMap.tsx      # MapLibre + parcel drawing
│       │   ├── viewer/BuildingViewer.tsx   # Three.js 3D viewer
│       │   └── ui/                  # Wizard, massing picker, AI chat
│       └── lib/store.ts             # Zustand global state
│
└── backend/scripts/
    └── generate_training_data.py    # Batch blueprint label extraction
```

---

## Archetype System

Drop a JSON file into `backend/app/data/archetypes/` to define a new building type. The archetype overrides massing shape, facade style, window type, room constraints, and MEP rules — no code changes needed.

```json
{
  "id": "victorian_narrow_lot",
  "display_name": "Victorian Narrow Lot",
  "triggers": { "style": ["victorian", "queen_anne"], "max_lot_width_m": 9 },
  "massing": { "brief_shape": "rectangle", "arch_style": "classic_gabled" },
  "facade": { "window_style": "double_hung", "arch_style": "victorian" },
  "rooms": { "max_bedrooms": 4 }
}
```

---

## Training Data Pipeline

A Claude vision pipeline extracts structured labels from blueprint images to build a fine-tuning dataset.

```bash
cd backend
python scripts/generate_training_data.py --data-dir app/data
```

Each image produces a `training/{type}/{type}_NNN_label.json` with rooms, dimensions, style, and confidence score. Re-running skips already-labeled images automatically.

Current dataset: **51 labeled examples** across SFR, ADU, townhouse, and Victorian categories.

---

## Data Sources

| Data | Source | Cost |
|------|--------|------|
| Parcel polygons, roads, buildings | OpenStreetMap / Overpass API | Free |
| Geocoding | Nominatim | Free |
| FEMA flood zones | FEMA MSC ArcGIS REST | Free |
| Map tiles | OpenStreetMap raster | Free |

---

## Roadmap

- [ ] IFC export (ifcopenshell)
- [ ] DXF / PDF plan set generation
- [ ] Fine-tune model on blueprint extraction dataset
- [ ] City-specific permit rules (LA, SF, Oakland, San Jose)
- [ ] Structural layout (columns, shear walls, hold-downs)
- [ ] Clash detection
