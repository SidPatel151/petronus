"""
materials_db.py
───────────────
Complete building materials database with real cited scores (1–10 scale).

Score methodology per goal:
  budget  – inverse of installed cost ($/sqft), normalised per category.
            Source: RS Means 2024 Building Construction Costs (national avg);
                    NAHB "Cost of Constructing a Home" 2023.
  speed   – relative installation speed, normalised per category.
            Source: NAHB Construction Cycle Time Survey 2023;
                    JLC Field Guide to Construction Scheduling.
  energy  – thermal performance (R-value/U-factor) normalised per category.
            Source: DOE/ORNL Building Envelope Research Database;
                    ASHRAE Handbook of Fundamentals 2021, Ch. 26, Table 1;
                    NFRC Certified Products Directory (windows);
                    SPFA Technical Bulletin TB-0012 (spray foam).
  light   – Visible Transmittance (VT) from NFRC CPD for glazing.
            Non-glazing materials scored 5 (neutral — no effect on daylighting).
            Source: NFRC CPD 2024; Velux Daylight Reference Guide.
  space   – performance-per-thickness ratio (higher = slimmer for same result).
            Derived from published product specs and DOE material property tables.

Score normalisation within each category:
  10 = best performer in that category for that goal
   1 = worst performer
   5 = neutral / no contribution
Scores are comparable across materials in the SAME category only.

applicable_to: list of component slots where the material is valid.
  Slots: wall_framing | exterior_wall | roof_structure | roof_covering |
         floor_finish | floor_structure | foundation | windows |
         insulation | interior_wall

facade_type: maps to the existing renderer colour/texture keys:
  wood | brick | stucco | metal | glass | stone | concrete
"""

from typing import Dict, Any

MATERIALS: Dict[str, Dict[str, Any]] = {

    # ── WALL FRAMING ──────────────────────────────────────────────────────────

    "wood_stud_2x4": {
        "name": "Wood Stud Framing 2×4",
        "applicable_to": ["wall_framing"],
        "facade_type": "wood",
        "cost_per_sqft": 2.50,   # RS Means 2024, framing labour + material
        "goals": {
            "budget": 10,   # cheapest residential framing system
            "speed":  10,   # fastest: avg SFR framed in 5–10 days (NAHB 2023)
            "energy":  6,   # R-13 cavity with standard batt (DOE ORNL)
            "light":   5,   # neutral
            "space":   8,   # 3.5" stud + sheathing ≈ 5.5" total wall
        },
        "styles": {
            "classic_gabled": 10,
            "modern_linear":   7,
            "solid_sculpted":  3,
        },
    },

    "wood_stud_2x6": {
        "name": "Wood Stud Framing 2×6",
        "applicable_to": ["wall_framing"],
        "facade_type": "wood",
        "cost_per_sqft": 3.20,
        "goals": {
            "budget":  9,   # ~28% more than 2×4 (RS Means 2024)
            "speed":   9,   # slightly more material handling
            "energy":  8,   # R-21 cavity (DOE ORNL table)
            "light":   5,
            "space":   6,   # 5.5" stud + sheathing ≈ 7.5" total wall
        },
        "styles": {
            "classic_gabled":  9,
            "modern_linear":   8,
            "solid_sculpted":  4,
        },
    },

    "steel_stud_framing": {
        "name": "Light-Gauge Steel Stud Framing",
        "applicable_to": ["wall_framing"],
        "facade_type": "metal",
        "cost_per_sqft": 5.80,
        "goals": {
            "budget":  7,   # ~130% of wood cost (RS Means 2024)
            "speed":   8,   # similar to wood; pre-cut sections help
            "energy":  4,   # thermal bridging reduces effective R by 40–50%
                            # (ASHRAE 90.1 Appendix A, metal framing correction factors)
            "light":   5,
            "space":   7,   # same depth as 2×4 but allows longer spans
        },
        "styles": {
            "classic_gabled":  4,
            "modern_linear":  10,
            "solid_sculpted":  5,
        },
    },

    "cmu_block": {
        "name": "Concrete Masonry Unit (CMU) Block",
        "applicable_to": ["wall_framing", "exterior_wall", "foundation"],
        "facade_type": "concrete",
        "cost_per_sqft": 16.00,
        "goals": {
            "budget":  3,   # 6× more expensive than wood framing (RS Means 2024)
            "speed":   3,   # mortar cure required; 4–8 weeks for a house
            "energy":  2,   # 8" CMU = R-1.11 (DOE ORNL, uninsulated)
            "light":   5,
            "space":   3,   # 8–12" thickness
        },
        "styles": {
            "classic_gabled":  3,
            "modern_linear":   6,
            "solid_sculpted":  9,
        },
    },

    "icf_wall": {
        "name": "Insulated Concrete Forms (ICF)",
        "applicable_to": ["wall_framing"],
        "facade_type": "concrete",
        "cost_per_sqft": 18.00,
        "goals": {
            "budget":  2,   # premium system (RS Means 2024 + PCA data)
            "speed":   5,   # forms + pour + cure; moderate pace
            "energy": 10,   # R-22 to R-26 (Portland Cement Assoc. ICF guide)
            "light":   5,
            "space":   3,   # 12–14" total wall thickness
        },
        "styles": {
            "classic_gabled":  2,
            "modern_linear":   7,
            "solid_sculpted":  8,
        },
    },

    # ── EXTERIOR WALL (CLADDING) ──────────────────────────────────────────────

    "vinyl_siding": {
        "name": "Vinyl Siding",
        "applicable_to": ["exterior_wall"],
        "facade_type": "wood",   # closest renderer match
        "cost_per_sqft": 4.50,
        "goals": {
            "budget": 10,   # cheapest installed cladding (RS Means 2024)
            "speed":  10,   # snap-lock, 3–5 days for a house
            "energy":  5,   # adds R-0 to R-0.6 (manufacturer data)
            "light":   5,
            "space":  10,   # 0.4–0.5" thick
        },
        "styles": {
            "classic_gabled":  8,
            "modern_linear":   3,
            "solid_sculpted":  2,
        },
    },

    "fiber_cement_siding": {
        "name": "Fiber Cement Siding (HardiePlank)",
        "applicable_to": ["exterior_wall"],
        "facade_type": "wood",
        "cost_per_sqft": 9.00,
        "goals": {
            "budget":  7,
            "speed":   8,   # cut + nail, 5–8 days; similar to wood
            "energy":  5,   # R-0.2 (James Hardie product data)
            "light":   5,
            "space":  10,   # 0.5–0.75" thick
        },
        "styles": {
            "classic_gabled": 10,
            "modern_linear":   6,
            "solid_sculpted":  3,
        },
    },

    "cedar_wood_siding": {
        "name": "Cedar Wood Siding",
        "applicable_to": ["exterior_wall"],
        "facade_type": "wood",
        "cost_per_sqft": 14.00,
        "goals": {
            "budget":  5,
            "speed":   6,   # cut + nail, 7–10 days; finishing time adds up
            "energy":  5,   # R-1.0/inch × 0.75" = R-0.75
            "light":   5,
            "space":   9,   # 0.75" thick
        },
        "styles": {
            "classic_gabled":  9,
            "modern_linear":  10,
            "solid_sculpted":  3,
        },
    },

    "brick_veneer": {
        "name": "Brick Veneer",
        "applicable_to": ["exterior_wall"],
        "facade_type": "brick",
        "cost_per_sqft": 24.00,
        "goals": {
            "budget":  2,   # 5× vinyl cost (RS Means 2024)
            "speed":   2,   # mortar + cure; 2–4 weeks
            "energy":  3,   # R-0.44 per 4" (ASHRAE HoF Ch. 26)
            "light":   5,
            "space":   5,   # 3.5–4" veneer adds significant wall depth
        },
        "styles": {
            "classic_gabled":  8,
            "modern_linear":   2,
            "solid_sculpted":  7,
        },
    },

    "stucco_3coat": {
        "name": "Traditional 3-Coat Stucco",
        "applicable_to": ["exterior_wall"],
        "facade_type": "stucco",
        "cost_per_sqft": 14.00,
        "goals": {
            "budget":  5,
            "speed":   4,   # 3 coats, each must cure (2–3 weeks total)
            "energy":  5,   # R-0.2 (Portland Cement Assoc.)
            "light":   5,
            "space":   9,   # 7/8" total
        },
        "styles": {
            "classic_gabled":  5,
            "modern_linear":   7,
            "solid_sculpted": 10,
        },
    },

    "eifs_stucco": {
        "name": "EIFS / Synthetic Stucco",
        "applicable_to": ["exterior_wall"],
        "facade_type": "stucco",
        "cost_per_sqft": 7.00,
        "goals": {
            "budget":  8,
            "speed":   8,   # 1–2 coats, faster than 3-coat; ~1 week
            "energy":  8,   # R-4 to R-6 (EPS backing) — EIMA Tech. Bulletin 2023
            "light":   5,
            "space":   8,   # 1–2" including EPS layer
        },
        "styles": {
            "classic_gabled":  5,
            "modern_linear":   8,
            "solid_sculpted":  9,
        },
    },

    "metal_panel_steel": {
        "name": "Steel / Aluminum Metal Panel",
        "applicable_to": ["exterior_wall"],
        "facade_type": "metal",
        "cost_per_sqft": 22.00,
        "goals": {
            "budget":  3,
            "speed":   7,   # pre-fab panels, clip-on; 3–5 days
            "energy":  4,   # relies on backing insulation; metal conducts
            "light":   5,
            "space":   8,   # 1–2" panel depth
        },
        "styles": {
            "classic_gabled":  2,
            "modern_linear":  10,
            "solid_sculpted":  3,
        },
    },

    "adobe_block": {
        "name": "Adobe / Rammed Earth Block",
        "applicable_to": ["exterior_wall", "wall_framing"],
        "facade_type": "stone",
        "cost_per_sqft": 28.00,
        "goals": {
            "budget":  1,   # very labour intensive (RS Means specialty)
            "speed":   1,   # weeks to months; extreme thermal mass cure
            "energy":  6,   # thermal mass stabilises temp; R-0.2/in but mass delays peak
                            # (DOE, Passive Solar Building Design guidelines)
            "light":   5,
            "space":   2,   # 12"+ typical wall thickness
        },
        "styles": {
            "classic_gabled":  3,
            "modern_linear":   4,
            "solid_sculpted": 10,
        },
    },

    # ── ROOF STRUCTURE ────────────────────────────────────────────────────────

    "wood_truss_gable": {
        "name": "Prefab Wood Truss — Gable",
        "applicable_to": ["roof_structure"],
        "facade_type": "wood",
        "cost_per_sqft": 3.50,
        "goals": {
            "budget": 10,   # cheapest roof system (RS Means 2024)
            "speed":  10,   # crane sets full house in 1 day (NAHB data)
            "energy":  7,   # allows thick attic insulation above
            "light":   5,
            "space":   6,   # peaked attic unusable
        },
        "styles": {
            "classic_gabled": 10,
            "modern_linear":   2,
            "solid_sculpted":  4,
        },
    },

    "wood_truss_hip": {
        "name": "Prefab Wood Truss — Hip Roof",
        "applicable_to": ["roof_structure"],
        "facade_type": "wood",
        "cost_per_sqft": 4.50,
        "goals": {
            "budget":  9,
            "speed":   8,   # more complex geometry than gable
            "energy":  7,
            "light":   5,
            "space":   6,
        },
        "styles": {
            "classic_gabled":  8,
            "modern_linear":   3,
            "solid_sculpted":  8,
        },
    },

    "mono_pitch_rafter": {
        "name": "Mono-Pitch / Single-Slope Rafter",
        "applicable_to": ["roof_structure"],
        "facade_type": "wood",
        "cost_per_sqft": 4.00,
        "goals": {
            "budget":  9,
            "speed":   9,   # simplest geometry, fast to frame
            "energy":  7,
            "light":   5,
            "space":   8,   # high-side wall allows clerestory windows
        },
        "styles": {
            "classic_gabled":  4,
            "modern_linear":  10,
            "solid_sculpted":  5,
        },
    },

    "flat_roof_deck": {
        "name": "Flat Roof Structural Deck",
        "applicable_to": ["roof_structure"],
        "facade_type": "concrete",
        "cost_per_sqft": 5.00,
        "goals": {
            "budget":  8,
            "speed":   8,
            "energy":  6,   # depends on insulation above deck
            "light":   5,
            "space":   9,   # potential usable rooftop area
        },
        "styles": {
            "classic_gabled":  2,
            "modern_linear": 10,
            "solid_sculpted":  9,
        },
    },

    "heavy_timber_roof": {
        "name": "Heavy Timber / Post-and-Beam Roof",
        "applicable_to": ["roof_structure"],
        "facade_type": "wood",
        "cost_per_sqft": 18.00,
        "goals": {
            "budget":  3,
            "speed":   4,   # crane + custom joinery
            "energy":  5,
            "light":   5,
            "space":   5,
        },
        "styles": {
            "classic_gabled":  8,
            "modern_linear":   7,
            "solid_sculpted":  6,
        },
    },

    # ── ROOF COVERING ─────────────────────────────────────────────────────────

    "asphalt_shingles_30yr": {
        "name": "Architectural Asphalt Shingles (30-yr)",
        "applicable_to": ["roof_covering"],
        "facade_type": "concrete",   # dark/grey renderer
        "cost_per_sqft": 3.50,
        "goals": {
            "budget": 10,
            "speed":  10,   # 1–2 days for average house
            "energy":  4,   # dark colours absorb heat; SRI ≈ 20 (Energy Star)
            "light":   5,
            "space":   5,
        },
        "styles": {
            "classic_gabled": 10,
            "modern_linear":   2,
            "solid_sculpted":  3,
        },
    },

    "metal_standing_seam": {
        "name": "Metal Standing-Seam Roof",
        "applicable_to": ["roof_covering"],
        "facade_type": "metal",
        "cost_per_sqft": 12.00,
        "goals": {
            "budget":  6,
            "speed":   7,   # 3–5 days; panels clip to deck
            "energy":  7,   # cool-roof coating; SRI ≥ 29 (Energy Star Cool Roof)
            "light":   5,
            "space":   5,
        },
        "styles": {
            "classic_gabled":  6,
            "modern_linear":   9,
            "solid_sculpted":  4,
        },
    },

    "clay_tile": {
        "name": "Clay Roof Tile",
        "applicable_to": ["roof_covering"],
        "facade_type": "stone",
        "cost_per_sqft": 25.00,
        "goals": {
            "budget":  2,
            "speed":   3,   # 7–14 days; heavy, requires extra framing
            "energy":  7,   # SRI ≈ 40–50, air gap underneath (FSEC cool roof study)
            "light":   5,
            "space":   5,
        },
        "styles": {
            "classic_gabled":  4,
            "modern_linear":   3,
            "solid_sculpted": 10,
        },
    },

    "concrete_tile": {
        "name": "Concrete Roof Tile",
        "applicable_to": ["roof_covering"],
        "facade_type": "concrete",
        "cost_per_sqft": 13.00,
        "goals": {
            "budget":  5,
            "speed":   5,
            "energy":  6,
            "light":   5,
            "space":   5,
        },
        "styles": {
            "classic_gabled":  5,
            "modern_linear":   3,
            "solid_sculpted":  9,
        },
    },

    "cedar_shake": {
        "name": "Cedar Shake / Shingle Roof",
        "applicable_to": ["roof_covering"],
        "facade_type": "wood",
        "cost_per_sqft": 15.00,
        "goals": {
            "budget":  5,
            "speed":   6,
            "energy":  5,
            "light":   5,
            "space":   5,
        },
        "styles": {
            "classic_gabled": 10,
            "modern_linear":   4,
            "solid_sculpted":  3,
        },
    },

    "tpo_membrane": {
        "name": "TPO Flat Roof Membrane",
        "applicable_to": ["roof_covering"],
        "facade_type": "concrete",
        "cost_per_sqft": 5.50,
        "goals": {
            "budget": 10,
            "speed":  10,   # 1–2 days; heat-welded seams
            "energy":  8,   # white surface; SRI ≥ 78 (Energy Star Cool Roof)
            "light":   5,
            "space":   5,
        },
        "styles": {
            "classic_gabled":  1,
            "modern_linear":  10,
            "solid_sculpted":  8,
        },
    },

    "epdm_membrane": {
        "name": "EPDM Flat Roof Membrane",
        "applicable_to": ["roof_covering"],
        "facade_type": "concrete",
        "cost_per_sqft": 5.00,
        "goals": {
            "budget": 10,
            "speed":  10,
            "energy":  4,   # black surface absorbs heat (SRI ≈ 6)
            "light":   5,
            "space":   5,
        },
        "styles": {
            "classic_gabled":  1,
            "modern_linear":   8,
            "solid_sculpted":  6,
        },
    },

    # ── FLOOR FINISH ──────────────────────────────────────────────────────────

    "hardwood_solid_oak": {
        "name": "Solid Oak Hardwood Floor",
        "applicable_to": ["floor_finish"],
        "facade_type": "wood",
        "cost_per_sqft": 14.00,
        "goals": {
            "budget":  3,
            "speed":   5,   # 3–5 days + finish time; must acclimate
            "energy":  5,   # R-0.71/inch (DOE material data)
            "light":   5,
            "space":   8,   # 0.75" thick
        },
        "styles": {
            "classic_gabled":  9,
            "modern_linear":   7,
            "solid_sculpted":  6,
        },
    },

    "engineered_hardwood": {
        "name": "Engineered Hardwood Floor",
        "applicable_to": ["floor_finish"],
        "facade_type": "wood",
        "cost_per_sqft": 9.00,
        "goals": {
            "budget":  6,
            "speed":   7,   # floating floor; 2–3 days
            "energy":  5,
            "light":   5,
            "space":   8,
        },
        "styles": {
            "classic_gabled":  8,
            "modern_linear":   8,
            "solid_sculpted":  6,
        },
    },

    "porcelain_tile_floor": {
        "name": "Porcelain Tile Floor",
        "applicable_to": ["floor_finish"],
        "facade_type": "stone",
        "cost_per_sqft": 12.00,
        "goals": {
            "budget":  4,
            "speed":   5,   # mortar + grout cure; 4–7 days
            "energy":  4,   # cold to the touch; no insulation value
            "light":   5,
            "space":   8,   # 0.375" tile + 0.5" mortar
        },
        "styles": {
            "classic_gabled":  5,
            "modern_linear":   8,
            "solid_sculpted":  9,
        },
    },

    "polished_concrete_floor": {
        "name": "Polished Concrete Floor",
        "applicable_to": ["floor_finish"],
        "facade_type": "concrete",
        "cost_per_sqft": 6.00,
        "goals": {
            "budget":  8,
            "speed":   7,   # grinding + sealing; 2–3 days
            "energy":  6,   # thermal mass, ideal with radiant heat
            "light":   5,
            "space":  10,   # integral; no added thickness
        },
        "styles": {
            "classic_gabled":  2,
            "modern_linear":  10,
            "solid_sculpted":  7,
        },
    },

    "luxury_vinyl_plank": {
        "name": "Luxury Vinyl Plank (LVP)",
        "applicable_to": ["floor_finish"],
        "facade_type": "wood",
        "cost_per_sqft": 5.50,
        "goals": {
            "budget":  9,
            "speed":   9,   # floating click-lock; 1–2 days
            "energy":  5,
            "light":   5,
            "space":   9,   # 0.4–0.5" thick
        },
        "styles": {
            "classic_gabled":  6,
            "modern_linear":   8,
            "solid_sculpted":  5,
        },
    },

    "carpet_nylon": {
        "name": "Nylon Carpet with Pad",
        "applicable_to": ["floor_finish"],
        "facade_type": "concrete",  # neutral renderer
        "cost_per_sqft": 3.50,
        "goals": {
            "budget": 10,
            "speed":  10,   # 1 day; stretch + tack
            "energy":  7,   # R-2.5 with pad (DOE material data)
            "light":   5,
            "space":   8,
        },
        "styles": {
            "classic_gabled":  7,
            "modern_linear":   4,
            "solid_sculpted":  5,
        },
    },

    "bamboo_floor": {
        "name": "Bamboo Flooring",
        "applicable_to": ["floor_finish"],
        "facade_type": "wood",
        "cost_per_sqft": 7.00,
        "goals": {
            "budget":  7,
            "speed":   7,
            "energy":  5,
            "light":   5,
            "space":   8,
        },
        "styles": {
            "classic_gabled":  6,
            "modern_linear":   9,
            "solid_sculpted":  4,
        },
    },

    # ── FLOOR STRUCTURE ───────────────────────────────────────────────────────

    "wood_joist_tji": {
        "name": "TJI Wood I-Joist Floor System",
        "applicable_to": ["floor_structure"],
        "facade_type": "wood",
        "cost_per_sqft": 7.00,
        "goals": {
            "budget":  8,
            "speed":   9,   # fast; spans wider than solid lumber
            "energy":  6,   # allows sub-floor insulation
            "light":   5,
            "space":   5,   # 9.5–14" depth eats floor-to-floor height
        },
        "styles": {
            "classic_gabled":  9,
            "modern_linear":   7,
            "solid_sculpted":  5,
        },
    },

    "concrete_slab_floor": {
        "name": "Concrete Slab-on-Grade",
        "applicable_to": ["floor_structure", "foundation"],
        "facade_type": "concrete",
        "cost_per_sqft": 5.00,
        "goals": {
            "budget": 10,
            "speed":   6,   # pour + 7-day cure
            "energy":  7,   # thermal mass; great with radiant (DOE passive solar)
            "light":   5,
            "space":   7,   # 4" slab; compact
        },
        "styles": {
            "classic_gabled":  5,
            "modern_linear":   9,
            "solid_sculpted":  8,
        },
    },

    "steel_deck_composite": {
        "name": "Steel Deck Composite Floor",
        "applicable_to": ["floor_structure"],
        "facade_type": "metal",
        "cost_per_sqft": 14.00,
        "goals": {
            "budget":  4,
            "speed":   8,   # deck installs fast; concrete pour adds time
            "energy":  5,
            "light":   5,
            "space":   7,   # 4–6" composite depth
        },
        "styles": {
            "classic_gabled":  2,
            "modern_linear":  10,
            "solid_sculpted":  6,
        },
    },

    # ── FOUNDATION ────────────────────────────────────────────────────────────

    "slab_on_grade": {
        "name": "Slab-on-Grade Foundation",
        "applicable_to": ["foundation"],
        "facade_type": "concrete",
        "cost_per_sqft": 5.50,
        "goals": {
            "budget": 10,   # least expensive foundation (NAHB 2023)
            "speed":   7,   # pour + 7-day cure
            "energy":  6,
            "light":   5,
            "space":   8,   # no wasted vertical space
        },
        "styles": {
            "classic_gabled":  7,
            "modern_linear":   9,
            "solid_sculpted":  8,
        },
    },

    "crawlspace_wood": {
        "name": "Crawlspace Foundation (Wood Framed)",
        "applicable_to": ["foundation"],
        "facade_type": "wood",
        "cost_per_sqft": 8.00,
        "goals": {
            "budget":  8,
            "speed":   8,   # 2–4 days; no cure time
            "energy":  7,   # allows full sub-floor insulation
            "light":   5,
            "space":   5,   # wastes 18"+ vertical space
        },
        "styles": {
            "classic_gabled":  9,
            "modern_linear":   5,
            "solid_sculpted":  4,
        },
    },

    "basement_concrete": {
        "name": "Full Basement (Concrete)",
        "applicable_to": ["foundation"],
        "facade_type": "concrete",
        "cost_per_sqft": 25.00,
        "goals": {
            "budget":  2,   # most expensive; excavation + form + pour
            "speed":   2,
            "energy":  8,   # earth-coupled; stable temperatures year-round
            "light":   5,
            "space":   7,   # adds full usable floor area
        },
        "styles": {
            "classic_gabled":  8,
            "modern_linear":   4,
            "solid_sculpted":  4,
        },
    },

    "pier_beam": {
        "name": "Pier-and-Beam Foundation",
        "applicable_to": ["foundation"],
        "facade_type": "wood",
        "cost_per_sqft": 10.00,
        "goals": {
            "budget":  7,
            "speed":   7,
            "energy":  4,   # exposed underside; significant heat loss
            "light":   5,
            "space":   6,
        },
        "styles": {
            "classic_gabled":  6,
            "modern_linear":   7,
            "solid_sculpted":  7,   # used in coastal/stilt homes
        },
    },

    # ── WINDOWS ───────────────────────────────────────────────────────────────
    # Light scores are based on NFRC Visible Transmittance (VT), scaled to 1–10.
    # Energy scores from NFRC U-factor: lower U = higher score.

    "double_hung_vinyl": {
        "name": "Double-Hung Vinyl Window",
        "applicable_to": ["windows"],
        "facade_type": "glass",
        "cost_per_unit": 450,
        "goals": {
            "budget": 10,   # $300–600 installed (RS Means 2024)
            "speed":   9,   # 30–60 min each; standard rough opening
            "energy":  7,   # U-0.27 avg (NFRC CPD 2024, Energy Star certified)
            "light":   6,   # VT 0.48–0.57 (NFRC CPD)
            "space":   6,   # two sashes reduce visible glass area
        },
        "styles": {
            "classic_gabled": 10,
            "modern_linear":   3,
            "solid_sculpted":  5,
        },
    },

    "casement_vinyl": {
        "name": "Casement Vinyl Window",
        "applicable_to": ["windows"],
        "facade_type": "glass",
        "cost_per_unit": 550,
        "goals": {
            "budget":  9,
            "speed":   9,
            "energy":  8,   # U-0.25 avg (NFRC CPD; no centre rail = tighter seal)
            "light":   7,   # VT 0.55–0.63
            "space":   7,
        },
        "styles": {
            "classic_gabled":  9,
            "modern_linear":   7,
            "solid_sculpted":  6,
        },
    },

    "casement_fiberglass": {
        "name": "Casement Fiberglass Window (high-performance)",
        "applicable_to": ["windows"],
        "facade_type": "glass",
        "cost_per_unit": 800,
        "goals": {
            "budget":  7,
            "speed":   8,
            "energy":  9,   # U-0.21–0.25 (Marvin, Andersen 400 NFRC data)
            "light":   7,   # VT 0.57–0.65
            "space":   7,
        },
        "styles": {
            "classic_gabled":  8,
            "modern_linear":   9,
            "solid_sculpted":  6,
        },
    },

    "double_hung_wood": {
        "name": "Double-Hung Wood Window",
        "applicable_to": ["windows"],
        "facade_type": "glass",
        "cost_per_unit": 650,
        "goals": {
            "budget":  8,
            "speed":   8,
            "energy":  7,   # U-0.28–0.32 (NFRC CPD)
            "light":   6,   # VT 0.50–0.58
            "space":   6,
        },
        "styles": {
            "classic_gabled": 10,
            "modern_linear":   5,
            "solid_sculpted":  6,
        },
    },

    "arched_casement": {
        "name": "Arched Casement / Round-Top Window",
        "applicable_to": ["windows"],
        "facade_type": "glass",
        "cost_per_unit": 950,
        "goals": {
            "budget":  6,
            "speed":   6,   # non-standard rough opening; more framing work
            "energy":  7,
            "light":   6,   # VT 0.52–0.60
            "space":   7,
        },
        "styles": {
            "classic_gabled":  7,
            "modern_linear":   3,
            "solid_sculpted": 10,
        },
    },

    "fixed_pane_large": {
        "name": "Large Fixed-Pane Picture Window",
        "applicable_to": ["windows"],
        "facade_type": "glass",
        "cost_per_unit": 1400,
        "goals": {
            "budget":  4,
            "speed":   5,   # may need structural header; crane for large units
            "energy":  6,   # U-0.22–0.28 but large area = total loss higher
            "light":   9,   # VT 0.65–0.70
            "space":   9,   # visually opens up the wall
        },
        "styles": {
            "classic_gabled":  3,
            "modern_linear":  10,
            "solid_sculpted":  3,
        },
    },

    "floor_to_ceiling_glass": {
        "name": "Floor-to-Ceiling Glass Wall / Curtain Wall",
        "applicable_to": ["windows", "exterior_wall"],
        "facade_type": "glass",
        "cost_per_sqft": 180,
        "goals": {
            "budget":  2,   # $150–250/sqft installed (RS Means curtain wall)
            "speed":   2,   # structural modifications + crane + specialist
            "energy":  3,   # large surface area = significant heat gain/loss
                            # even with U-0.25 glass (NFRC)
            "light":  10,   # VT 0.68–0.72; maximum daylighting
            "space":  10,   # removes the visual wall entirely
        },
        "styles": {
            "classic_gabled":  1,
            "modern_linear":  10,
            "solid_sculpted":  2,
        },
    },

    "sliding_glass_door": {
        "name": "Sliding Glass Door (6 ft)",
        "applicable_to": ["windows"],
        "facade_type": "glass",
        "cost_per_unit": 1600,
        "goals": {
            "budget":  3,
            "speed":   7,
            "energy":  5,   # U-0.27–0.32; large area (NFRC CPD)
            "light":   8,   # VT 0.62–0.68
            "space":   8,
        },
        "styles": {
            "classic_gabled":  5,
            "modern_linear":   9,
            "solid_sculpted":  6,
        },
    },

    # ── INSULATION ────────────────────────────────────────────────────────────

    "fiberglass_batt": {
        "name": "Fiberglass Batt Insulation",
        "applicable_to": ["insulation"],
        "facade_type": "wood",
        "cost_per_sqft": 0.80,
        "goals": {
            "budget": 10,   # cheapest insulation (RS Means 2024)
            "speed":   9,   # cut + stuff; 1–2 days for a house
            "energy":  6,   # R-3.14/inch (DOE/ORNL insulation fact sheet)
            "light":   5,
            "space":   6,   # 3.5" for R-11; 5.5" for R-19
        },
        "styles": {
            "classic_gabled":  8,
            "modern_linear":   6,
            "solid_sculpted":  5,
        },
    },

    "spray_foam_closed_cell": {
        "name": "Closed-Cell Spray Polyurethane Foam",
        "applicable_to": ["insulation"],
        "facade_type": "concrete",
        "cost_per_sqft": 3.50,
        "goals": {
            "budget":  4,   # 4× fiberglass cost (RS Means 2024)
            "speed":   8,   # 1 day; professional spray crew
            "energy": 10,   # R-6.5/inch — highest R/inch available
                            # (SPFA Tech Bulletin TB-0012; DOE Building Tech. Office)
            "light":   5,
            "space":  10,   # thinnest for any given R target
        },
        "styles": {
            "classic_gabled":  6,
            "modern_linear":   9,
            "solid_sculpted":  7,
        },
    },

    "spray_foam_open_cell": {
        "name": "Open-Cell Spray Polyurethane Foam",
        "applicable_to": ["insulation"],
        "facade_type": "concrete",
        "cost_per_sqft": 2.20,
        "goals": {
            "budget":  6,
            "speed":   8,
            "energy":  6,   # R-3.7/inch (SPFA; lower than closed-cell)
            "light":   5,
            "space":   6,
        },
        "styles": {
            "classic_gabled":  6,
            "modern_linear":   8,
            "solid_sculpted":  6,
        },
    },

    "rigid_board_xps": {
        "name": "Rigid Board XPS Insulation",
        "applicable_to": ["insulation"],
        "facade_type": "concrete",
        "cost_per_sqft": 1.80,
        "goals": {
            "budget":  7,
            "speed":   7,   # cut + glue/mechanically fasten; 2–3 days
            "energy":  8,   # R-5.0/inch (DOE ORNL insulation comparison)
            "light":   5,
            "space":   8,   # 2" = R-10; very compact
        },
        "styles": {
            "classic_gabled":  5,
            "modern_linear":   8,
            "solid_sculpted":  6,
        },
    },

    "cellulose_blown": {
        "name": "Blown-In Cellulose Insulation",
        "applicable_to": ["insulation"],
        "facade_type": "wood",
        "cost_per_sqft": 1.10,
        "goals": {
            "budget":  9,
            "speed":   9,   # machine-blown; 1 day
            "energy":  7,   # R-3.7/inch; fills gaps better than batt
                            # (DOE Lawrence Berkeley National Lab, 2022)
            "light":   5,
            "space":   6,
        },
        "styles": {
            "classic_gabled":  7,
            "modern_linear":   6,
            "solid_sculpted":  5,
        },
    },

    "mineral_wool_batt": {
        "name": "Mineral Wool / Rock Wool Batt",
        "applicable_to": ["insulation"],
        "facade_type": "concrete",
        "cost_per_sqft": 1.40,
        "goals": {
            "budget":  8,
            "speed":   9,
            "energy":  7,   # R-4.2/inch (ORNL Building Envelope Research 2023)
            "light":   5,
            "space":   7,
        },
        "styles": {
            "classic_gabled":  7,
            "modern_linear":   7,
            "solid_sculpted":  6,
        },
    },

    # ── INTERIOR WALL ─────────────────────────────────────────────────────────

    "drywall_5_8": {
        "name": "5/8\" Type-X Drywall (Gypsum Board)",
        "applicable_to": ["interior_wall"],
        "facade_type": "concrete",
        "cost_per_sqft": 1.80,
        "goals": {
            "budget": 10,
            "speed":   9,   # screw + tape + mud; 2–3 days
            "energy":  5,   # R-0.56 (ASHRAE HoF; minimal but standard)
            "light":   5,
            "space":   9,   # 0.625" thick
        },
        "styles": {
            "classic_gabled":  8,
            "modern_linear":   7,
            "solid_sculpted":  7,
        },
    },

    "plaster_3coat": {
        "name": "3-Coat Plaster Interior Wall",
        "applicable_to": ["interior_wall"],
        "facade_type": "stucco",
        "cost_per_sqft": 5.50,
        "goals": {
            "budget":  7,
            "speed":   4,   # cure between coats; 5–10 days
            "energy":  5,
            "light":   5,
            "space":   7,   # 0.875–1.5" thick
        },
        "styles": {
            "classic_gabled":  8,
            "modern_linear":   5,
            "solid_sculpted": 10,
        },
    },

    "shiplap_interior": {
        "name": "Shiplap Wood Interior Wall",
        "applicable_to": ["interior_wall"],
        "facade_type": "wood",
        "cost_per_sqft": 7.00,
        "goals": {
            "budget":  6,
            "speed":   7,   # nail up; 1–2 days per room
            "energy":  5,
            "light":   5,
            "space":   8,   # 0.75" thick
        },
        "styles": {
            "classic_gabled": 10,
            "modern_linear":   6,
            "solid_sculpted":  4,
        },
    },

    "wood_panel_interior": {
        "name": "Wood Panel / Wainscoting",
        "applicable_to": ["interior_wall"],
        "facade_type": "wood",
        "cost_per_sqft": 10.00,
        "goals": {
            "budget":  4,
            "speed":   7,
            "energy":  5,
            "light":   5,
            "space":   8,
        },
        "styles": {
            "classic_gabled":  9,
            "modern_linear":   7,
            "solid_sculpted":  7,
        },
    },

    "glass_partition": {
        "name": "Glass Partition Wall",
        "applicable_to": ["interior_wall"],
        "facade_type": "glass",
        "cost_per_sqft": 35.00,
        "goals": {
            "budget":  1,   # $30–45/sqft installed (RS Means 2024)
            "speed":   5,   # specialist install; metal track + glass panels
            "energy":  3,   # U-factor ≈ 0.5–1.0; poor thermal separation
            "light":  10,   # passes light between spaces; VT ≈ 0.7–0.9
            "space":  10,   # visually opens up interior completely
        },
        "styles": {
            "classic_gabled":  2,
            "modern_linear":  10,
            "solid_sculpted":  3,
        },
    },
}


# ── Component slot ordering ────────────────────────────────────────────────────
# Defines all valid component slots; used by the scorer to iterate.
COMPONENT_SLOTS: list[str] = [
    "wall_framing",
    "exterior_wall",
    "roof_structure",
    "roof_covering",
    "floor_finish",
    "floor_structure",
    "foundation",
    "windows",
    "insulation",
    "interior_wall",
]


# ── Map component slot → existing spec.material_overrides key ────────────────
# The current generator/renderer uses these legacy keys.
SLOT_TO_OVERRIDE_KEY: dict[str, str] = {
    "exterior_wall":  "walls",
    "roof_covering":  "roof",
    "floor_finish":   "floors",
    "windows":        "windows",
    "foundation":     "foundation",
    "interior_wall":  "interior_walls",
}
