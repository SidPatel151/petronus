"""
AI Chat endpoint — talks to Claude, detects building modification requests,
and returns both a reply and an optional spec_patch to trigger regeneration.
"""
import asyncio
import json
from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional, Dict, Any

router = APIRouter()

SYSTEM_PROMPT = """You are Petronus AI, an expert California residential architect and building engineer built into a BIM tool.

You can both ANSWER questions AND MODIFY the building by outputting a spec_patch.

VALID SPEC FIELDS you can change:
- stories: int (1-10)
- floor_to_floor_height_ft: float (8-14)
- structural_system: "wood" | "steel" | "concrete"
- priority: "cost" | "speed" | "daylight"
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

Examples:
- "make it 3 stories" → spec_patch: {"stories": 3}
- "use steel framing" → spec_patch: {"structural_system": "steel"}
- "make it L-shaped" → spec_patch: {"shape_hint": "l_shape"}
- "I need 8 units" → spec_patch: {"unit_count": 8}
- "prioritize natural light" → spec_patch: {"priority": "daylight"}
- "what's the seismic risk?" → spec_patch: {}

Be concise. When applying changes, briefly explain what changed and why it suits this site.
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
