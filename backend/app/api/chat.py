"""AI chat endpoint with constrained, regeneration-safe spec patches."""
import asyncio
import json
import logging
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter
from pydantic import BaseModel


router = APIRouter()
logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are Petronus AI, a California residential building-design assistant inside a conceptual BIM tool. You help users understand and modify a generated design, but you are not a licensed architect or engineer and must never describe this model as permit-approved or construction-ready.

CODE CONTEXT:
- Use the 2025 California Building Standards Code (Title 24) for applications filed during the 2026-2028 cycle unless the supplied project states another adopted cycle.
- Distinguish the California Residential Code from the California Building Code and distinguish NFPA 13D, NFPA 13R, and NFPA 13 based on occupancy and scope.
- California codes have local amendments. Treat AHJ requirements, utility rules, site conditions, product listings, and licensed-professional calculations as unresolved unless the supplied model documents them.
- Do not invent section numbers, universal thresholds, energy values, or seismic rules. Cite a section only when you are confident it applies to the stated occupancy, code cycle, and condition. Otherwise identify the subject and say it needs AHJ or professional verification.
- Automated compliance results are deterministic preflight evidence, not proof that every applicable provision was checked.

SAFETY PRIORITIES:
- Call out unresolved egress, accessibility, fire/life-safety, structural, geotechnical, flood, utility, electrical-load, HVAC-load, plumbing-pressure, hydraulic, and seismic work when relevant.
- Never claim a structural member, foundation, MEP size, brace, or connection is adequate without the required calculation and site inputs.
- When proposing a change, explain which downstream systems need regeneration or professional verification.

VALID SPEC FIELDS you may change:
- stories: integer 1-3
- floor_to_floor_height_ft: number 8-14
- structural_system: "wood" | "steel" | "concrete"
- priority: "cost" | "time" | "space" | "light" | "energy"
- target_gross_area_sqft: positive number
- unit_count: positive integer
- hvac_preference: "mini_split" | "rooftop"

Always return valid JSON exactly in this shape:
{
  "reply": "your concise conversational response",
  "spec_patch": {}
}

Include only supported fields that the user explicitly requested in spec_patch. For a question, use an empty patch. Explain material safety or coordination consequences without making approval claims. Use plain conversational text inside reply, with no markdown."""


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    site_context: Optional[Dict[str, Any]] = None
    building_model: Optional[Dict[str, Any]] = None
    clicked_building: Optional[Dict[str, Any]] = None


def _sanitize_spec_patch(value: Any) -> Dict[str, Any]:
    """Allow only fields and values accepted by ProjectSpec/the current UI."""
    if not isinstance(value, dict):
        return {}
    patch: Dict[str, Any] = {}
    enum_values = {
        "structural_system": {"wood", "steel", "concrete"},
        "priority": {"cost", "time", "space", "light", "energy"},
        "hvac_preference": {"mini_split", "rooftop"},
    }
    for field, allowed in enum_values.items():
        if value.get(field) in allowed:
            patch[field] = value[field]

    stories = value.get("stories")
    if isinstance(stories, int) and not isinstance(stories, bool) and 1 <= stories <= 3:
        patch["stories"] = stories
    units = value.get("unit_count")
    if isinstance(units, int) and not isinstance(units, bool) and 1 <= units <= 100:
        patch["unit_count"] = units
    for field, low, high in (
        ("floor_to_floor_height_ft", 8.0, 14.0),
        ("target_gross_area_sqft", 100.0, 50_000.0),
    ):
        candidate = value.get(field)
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            number = float(candidate)
            if low <= number <= high:
                patch[field] = number
    return patch


@router.post("/")
async def chat(body: ChatRequest):
    from app.core.config import settings

    if not settings.ANTHROPIC_API_KEY:
        return {
            "reply": "AI chat is not configured. Add ANTHROPIC_API_KEY to backend/.env and restart the API.",
            "spec_patch": {},
        }

    context = [SYSTEM_PROMPT]
    if body.site_context:
        site = body.site_context
        context.append(
            f"SITE: {float(site.get('area_sqft') or 0):.0f} sqft | "
            f"Flood: {site.get('flood_zone') or 'unknown'} | "
            f"Seismic SDC: {site.get('seismic_category') or 'unknown'} | "
            f"Wind: {site.get('wind_speed_mph') or 'unknown'} mph"
        )
        hazards = site.get("hazard_detail") or {}
        seismic = hazards.get("seismic") or {}
        if seismic.get("note"):
            context.append(f"Recorded seismic note: {seismic['note']}")
        weather = hazards.get("current_weather") or {}
        if weather.get("temp_f") is not None:
            context.append(
                f"Observed weather: {weather['temp_f']} F, "
                f"{weather.get('description') or 'description unavailable'}"
            )

    if body.building_model:
        building = body.building_model
        spec = building.get("spec") or {}
        context.append(
            f"CURRENT BUILDING: {len(building.get('levels') or [])} floors | "
            f"{len(building.get('rooms') or [])} rooms | "
            f"{len(building.get('mep_elements') or [])} MEP elements | "
            f"use={spec.get('building_use') or 'unknown'}, "
            f"stories={spec.get('stories') or 'unknown'}, "
            f"structure={spec.get('structural_system') or 'unknown'}, "
            f"area={spec.get('target_gross_area_sqft') or 'unknown'} sqft, "
            f"code_cycle={spec.get('code_cycle') or 'unknown'}"
        )
        errors = [
            issue for issue in (building.get("issues") or [])
            if isinstance(issue, dict) and issue.get("severity") == "error"
        ]
        if errors:
            context.append(
                "Current preflight errors: "
                + "; ".join(str(issue.get("message") or "") for issue in errors[:3])
            )

    if body.clicked_building:
        properties = body.clicked_building.get("properties") or {}
        context.append(
            f"CLICKED CONTEXT BUILDING: type={properties.get('building') or 'unknown'} | "
            f"stories={properties.get('building:levels') or 'unknown'} | "
            f"material={properties.get('building:material') or 'unknown'} | "
            f"height_m={properties.get('height_m') or 'unknown'}"
        )

    messages = [message.model_dump() for message in body.messages]
    if not messages:
        return {"reply": "Ask a question or describe the change you want.", "spec_patch": {}}

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = await asyncio.to_thread(
            client.messages.create,
            model="claude-haiku-4-5-20251001",
            max_tokens=700,
            system="\n".join(context),
            messages=messages,
        )
        raw = next(
            (block.text for block in response.content if getattr(block, "text", None)),
            "",
        ).strip()
    except Exception:
        logger.exception("AI chat provider call failed")
        return {
            "reply": "The AI service is temporarily unavailable. Your building model was not changed.",
            "spec_patch": {},
        }

    try:
        if raw.startswith("```"):
            raw = raw.split("```", 2)[1]
            if raw.lstrip().startswith("json"):
                raw = raw.lstrip()[4:]
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("AI response must be a JSON object")
        return {
            "reply": str(data.get("reply") or "I could not form a response."),
            "spec_patch": _sanitize_spec_patch(data.get("spec_patch")),
        }
    except (json.JSONDecodeError, ValueError, TypeError):
        return {"reply": raw or "I could not form a response.", "spec_patch": {}}
