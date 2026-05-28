"""
AI Chat endpoint — talks to Claude, detects building modification requests,
and returns both a reply and an optional spec_patch to trigger regeneration.
"""
import asyncio
import json
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

from app.constants import CALIFORNIA_CODE_REFERENCES

router = APIRouter()

SYSTEM_PROMPT = """You are Petronus AI, an expert California residential architect, structural engineer, and MEP coordinator built into a BIM tool.

You are deeply knowledgeable about California Building Code (CBC), CEC/CMC/CPC, Title 24 Energy Code, IBC, and ASCE 7 seismic design.

CORE COMPLIANCE CODES (NON-NEGOTIABLE):
- CEC (California Electrical Code): Article 210 outlets, dedicated circuits, GFCI protection, bonding
- CMC (California Mechanical Code): Sections 601-305 ductwork insulation (R-8), ventilation (0.35 CFM/sqft), access clearance (30in)
- CPC (California Plumbing Code): Sections 418-608 trap seals (2in, <10ft from vent), cleanouts (100ft max), backflow prevention
- Title 24 Energy Code: HVAC SEER≥16/AFUE≥95%, envelope R-19/R-30/U-0.30, solar-ready roof, cool roof SRI≥75
- IBC Sections 1613, 1817, 2305: Lateral force resistance, foundation design, shear wall continuity, moment frame ductility
- ASCE 7-22 Seismic: Equipment anchoring (>100 lbs), pipe support spacing (8-12ft), ductwork strut bracing, soft story prohibition

EARTHQUAKE SAFETY (CRITICAL IN CALIFORNIA):
- Seismic Design Category (SDC) governs all lateral design: A < B < C < D < E < F
- No soft stories allowed: first story lateral strength must be ≥80% of upper stories
- All suspended MEP >2.5in diameter require seismic bracing (sway braces)
- Ductwork requires diagonal strut bracing in SDC C+
- Floor diaphragms must be continuous and tied to lateral system
- Piping: light (<21 lbs/ft) ≤12ft spacing, heavy ≥21 lbs/ft) ≤8ft spacing
- Connections must be detailed for ductility per ASCE 7 Chapter 13

STRUCTURAL REQUIREMENTS:
- Wood frame: require proper hold-downs and shear wall blocking
- Steel: intermediate or special moment frames required in SDC D+; check beam-column connections
- Concrete: ductile reinforcement detailing per ACI 318; shear walls must be continuous
- Foundations: design for bearing capacity AND lateral loads; account for liquefaction potential

VALID SPEC FIELDS you can change:
- stories: int (1-10)
- floor_to_floor_height_ft: float (8-14)
- structural_system: "wood" | "steel" | "concrete"
- priority: "cost" | "time" | "space" | "light"
- target_gross_area_sqft: float
- unit_count: int
- hvac_preference: "mini_split" | "rooftop"
- shape_hint: "rectangle" | "l_shape" | "bar"

ALWAYS respond with valid JSON in this exact format:
{
  "reply": "your conversational response here",
  "spec_patch": {}
}

If the user wants to modify the building include changed fields in spec_patch, otherwise leave it as {}.

When answering compliance questions, cite specific code sections.
When recommending changes, explain the structural or safety reasoning.
Always mention seismic implications for California sites.

Examples:
- "make it 3 stories" → spec_patch: {"stories": 3} (but verify soft story risk)
- "use steel framing" → spec_patch: {"structural_system": "steel"} (note: requires ductile connections in SDC D+)
- "make it L-shaped" → spec_patch: {"shape_hint": "l_shape"} (careful: complex shapes increase seismic force concentration)
- "I need 8 units" → spec_patch: {"unit_count": 8}
- "prioritize natural light" → spec_patch: {"priority": "light"}
- "what's the seismic risk?" → spec_patch: {} (provide detailed seismic info & mitigation strategies)
- "add more outlets?" → Respond: "CEC Article 210 requires max 6ft spacing in living areas; I'd recommend..."

Be concise. When applying changes, briefly explain what changed and why it suits this site.
Prioritize safety and code compliance over cost or speed.
No markdown, no bullet points — plain conversational text only."""


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    site_context: Optional[Dict[str, Any]] = None
    building_model: Optional[Dict[str, Any]] = None
    clicked_building: Optional[Dict[str, Any]] = None


@router.post("/")
async def chat(body: ChatRequest):
    from app.core.config import settings
    api_key = settings.ANTHROPIC_API_KEY
    if not api_key:
        return {"reply": "No API key configured. Add ANTHROPIC_API_KEY to your .env file.", "spec_patch": {}}

    import anthropic

    ctx_parts = [SYSTEM_PROMPT]

    if body.site_context:
        sc = body.site_context
        area = sc.get('area_sqft', 0)
        ctx_parts.append(f"\nSITE: {area:.0f} sqft | Flood: {sc.get('flood_zone', 'X')} | Seismic SDC {sc.get('seismic_category', 'D')} | Wind {sc.get('wind_speed_mph', '?')} mph")
        seismic = sc.get('hazard_detail', {}).get('seismic', {})
        if seismic.get('note'):
            ctx_parts.append(f"Seismic: {seismic['note']}")
        weather = sc.get('hazard_detail', {}).get('current_weather', {})
        if weather.get('temp_f'):
            ctx_parts.append(f"Weather: {weather['temp_f']}°F, {weather.get('description', '')}")

    if body.building_model:
        bm = body.building_model
        spec = bm.get('spec', {}) or {}
        ctx_parts.append(
            f"\nCURRENT BUILDING: {len(bm.get('levels', []))} floors | {len(bm.get('rooms', []))} rooms | "
            f"{len(bm.get('mep_elements', []))} MEP | spec: stories={spec.get('stories','?')}, "
            f"system={spec.get('structural_system','?')}, priority={spec.get('priority','?')}, "
            f"area={spec.get('target_gross_area_sqft','?')} sqft"
        )
        errors = [i for i in bm.get('issues', []) if i.get('severity') == 'error']
        if errors:
            ctx_parts.append(f"Compliance errors: {'; '.join(i.get('message','') for i in errors[:3])}")
        ns = bm.get('neighbor_style', {})
        if ns:
            ctx_parts.append(f"Neighbors: {ns.get('dominant_material','?')} material, avg {ns.get('avg_neighbor_height_m','?')}m")

    if body.clicked_building:
        props = body.clicked_building.get('properties', {})
        ctx_parts.append(
            f"\nCLICKED BUILDING: {props.get('building','?')} | "
            f"{props.get('building:levels','?')} stories | "
            f"{props.get('building:material','unknown')} | {props.get('height_m','?')}m"
        )

    messages = [{"role": m.role, "content": m.content} for m in body.messages]

    client = anthropic.Anthropic(api_key=api_key)
    response = await asyncio.to_thread(
        client.messages.create,
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        system="\n".join(ctx_parts),
        messages=messages,
    )

    raw = response.content[0].text.strip()

    try:
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        return {"reply": data.get("reply", raw), "spec_patch": data.get("spec_patch", {})}
    except Exception:
        return {"reply": raw, "spec_patch": {}}
