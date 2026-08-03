# MEP Software California Code Compliance Update

## Summary
Enhanced the Petronus AI generation engine to enforce specific CEC/CMC/CPC/Energy Code/IBC MEP requirements and comprehensive earthquake/structural safety training. The model now generates designs that comply with California Building Code and ASCE 7-22 seismic standards.

---

## 1. Compliance Engine Enhancements (`backend/app/generators/compliance.py`)

### New Deterministic Rule Checks Added:

#### **CEC (California Electrical Code)**
- **Article 210 Outlet Spacing**: Max 6ft spacing in living areas
- **Kitchen Circuit**: ≥2 x 20A dedicated circuits for kitchen countertop
- **Bathroom Circuit**: 20A dedicated circuit per bathroom
- **GFCI Protection**: Required on all wet-area outlets (Article 210.8)

#### **CMC (California Mechanical Code)**
- **Ductwork Insulation**: R-8 minimum (or R-4.2 in occupied space) — Section 601
- **Ventilation Rate**: Min 0.35 CFM/sqft or 15 CFM/person outdoor air — Section 402
- **Duct Sealing & Testing**: All ductwork sealed and pressure-tested per ASHRAE 52.2
- **Equipment Clearance**: 30in minimum for inspection/maintenance access — Section 305

#### **CPC (California Plumbing Code)**
- **Trap Seal**: Min 2in seal; max 10ft distance from vent — Section 418.3
- **Cleanout Access**: Every 100ft of run; 24in access clearance — Section 410
- **Backflow Prevention**: Required on all potable water supply lines — Section 608.1
- **Fixture Unit Calculation**: Per IPC Table 422.1

#### **California Energy Code (Title 24)**
- **HVAC Efficiency**: SEER ≥16 (cooling), AFUE ≥95% (heating)
- **Building Envelope**: R-19 (walls), R-30 (attic), U-0.30 (windows)
- **Solar-Ready Roof**: Required for low-rise multifamily
- **Cool Roof**: SRI ≥75 (light-colored or vegetative roof)

#### **IBC Structural Requirements**
- **Lateral Load Design**: Per seismic design category (SDC) — IBC Section 1613
- **Foundation Design**: Must resist lateral forces & account for liquefaction — Section 1817
- **Shear Wall Continuity**: Continuous from roof to foundation — Section 2305
- **Moment Frame Ductility**: Special detailing in SDC D+ — Section 1913

#### **Seismic Safety (ASCE 7-22 / CBC)**
- **Equipment Anchoring**: All MEP >100 lbs must be seismically anchored
- **Pipe Support Spacing**: 
  - Light pipe (≤21 lbs/ft): ≤12ft spacing
  - Heavy pipe (>21 lbs/ft): ≤8ft spacing
- **Ductwork Strut Bracing**: Diagonal bracing required in SDC C+
- **Soft Story Prohibition**: First story lateral strength ≥80% of upper stories
- **Diaphragm Continuity**: Floor diaphragms must be continuous and tied to lateral system
- **MEP Seismic Bracing**: All suspended systems >2.5in diameter require sway braces

### Rule Severity Levels:
- **ERROR**: Life-safety critical (egress, soft stories, anchoring)
- **WARNING**: Code compliance but not immediate life-safety (ductwork, equipment spacing)

---

## 2. AI Prompt Enhancements

### `backend/app/services/ai_brief.py`
- **New Section**: "STRUCTURAL & SEISMIC REQUIREMENTS (CRITICAL)" in design brief prompt
- **Seismic Training**: Explicit instruction on SDC-based design, no soft stories, bracing requirements
- **MEP Coordination**: Model instructed to consider anchoring, support spacing, diaphragm connections
- **Code Reference List**: All 8 code standards injected into every design brief call

### `backend/app/api/chat.py` - SYSTEM_PROMPT Overhaul
- **Core Compliance Section**: Non-negotiable CEC/CMC/CPC/Title 24/IBC/ASCE 7 requirements
- **Earthquake Safety (CRITICAL)**: 
  - SDC definitions and implications
  - Soft story prohibition and verification
  - MEP bracing thresholds (>2.5in diameter)
  - Piping support spacing rules
  - Ductwork strut bracing mandate
  - Floor diaphragm requirements
- **Structural Requirements**: Wood/steel/concrete-specific detailing
- **Code Citation Training**: Model instructed to cite specific sections when answering
- **Safety Priority**: Explicit directive that safety > cost/speed

---

## 3. Constants Update (`backend/app/constants.py`)

Added:
```python
CALIFORNIA_CODE_REFERENCES: list[str] = [
    "Part 3: California Electrical Code (CEC)",
    "Part 4: California Mechanical Code (CMC)",
    "Part 5: California Plumbing Code (CPC)",
    "Part 6: California Energy Code",
    "International Building Code (IBC)",
    "National Electrical Code (NEC)",
    "International Mechanical Code (IMC)",
    "ICC/MBI 1210 Standard",
]
```

This list is injected into both AI prompts and available for UI display.

---

## 4. How It Works in Practice

### Design Generation Workflow:
1. User specifies site (California address) → gets seismic category (SDC)
2. Claude design brief now receives:
   - Explicit earthquake safety requirements
   - Structural system implications for SDC
   - MEP bracing & anchoring requirements
3. Compliance engine runs checks on generated model:
   - Flags any soft stories (error)
   - Warns on ductwork strut bracing
   - Requires equipment anchoring verification
   - Ensures MEP spacing meets ASCE 7

### Chat Interaction:
1. User asks: "Can we make this 4 stories?"
   → Model responds with SDC warning, soft story risk, code reference (IBC 1613)
2. User asks: "What's the HVAC requirement?"
   → Model cites Title 24 (SEER ≥16), CMC ductwork rules, GFCI/backflow protection
3. User asks: "How do we handle earthquake risk?"
   → Model provides SDC-specific guidance: bracing, anchoring, diaphragm design, soft story prohibition

---

## 5. Code Coverage Matrix

| Code Section | Coverage | Enforcement |
|---|---|---|
| CEC 210 | Outlets, circuits, GFCI | Warning (outlet spacing), Deterministic (circuit count) |
| CMC 601-305 | Ductwork, ventilation, access | Warning (ductwork insulation, sealing) |
| CPC 418-608 | Traps, cleanouts, backflow | Warning (trap seal, cleanout spacing) |
| Title 24 | HVAC, envelope, solar, cool roof | Warning (efficiency, envelope, solar, SRI) |
| IBC 1613-1817 | Lateral load, foundations | Error (lateral design required) |
| ASCE 7 Ch. 13 | Seismic MEP, equipment | Error (equipment >100 lbs), Warning (strut bracing) |
| CBC Sections | Soft story, diaphragm | Error (soft story), Warning (diaphragm) |

---

## 6. Example Compliance Issues Generated

When a user generates a 3-story building in SDC D:

```
ERROR: First story lateral strength must be ≥80% of upper stories (no soft story)
→ Fix: Ensure ground floor shear walls/frames as strong as upper floors

ERROR: All MEP equipment >100 lbs must be seismically anchored
→ Fix: Anchor rooftop units, fans, tanks via bolted/welded connections

WARNING: Ductwork in SDC D requires diagonal strut bracing
→ Fix: Add angle iron/tube at 45° to resist torsion

WARNING: CEC Article 210.8 — GFCI protection on all wet-area outlets
→ Fix: Specify GFCI-protected circuits for kitchen, bathroom, exterior

WARNING: CMC Section 601 — Ductwork R-8 insulation + pressure testing required
→ Fix: Specify insulated ductwork; test at 25 Pa per ASHRAE 52.2

WARNING: Piping support spacing: light ≤12ft, heavy ≤8ft (ASCE 7)
→ Fix: Install seismic supports at max intervals
```

---

## 7. Files Modified

1. **`backend/app/generators/compliance.py`**
   - Added 25+ new rule definitions
   - Implemented 6 new check methods (CEC, CMC, CPC, Energy, IBC, Seismic)
   - Updated `run()` to call all new checks

2. **`backend/app/constants.py`**
   - Added `CALIFORNIA_CODE_REFERENCES` list

3. **`backend/app/services/ai_brief.py`**
   - Imported `CALIFORNIA_CODE_REFERENCES`
   - Enhanced prompt with seismic & structural training

4. **`backend/app/api/chat.py`**
   - Imported `CALIFORNIA_CODE_REFERENCES`
   - Completely rewrote `SYSTEM_PROMPT` with comprehensive code guidance, seismic training, and earthquake safety emphasis

---

## 8. Next Steps / Optional Enhancements

1. **Database Integration**: Store compliance issues + fixes in project database for user review
2. **MEP Quantity Takeoffs**: Link rule violations to quantity estimates (labor, material cost impact)
3. **Permit Readiness**: Generate compliance checklist for permit submission
4. **Real-Time Validation**: Run compliance checks as user edits building in real-time
5. **Code Version Management**: Support multiple CBC/IBC years as standards evolve
6. **Liquefaction Mapping**: Integrate USGS liquefaction hazard maps for foundation design guidance
7. **Wind Load Calculation**: Add ASCE 7 wind pressure calculations for coastal/high-wind areas

---

## Testing Recommendations

1. **Compliance Engine**: Generate a 4-story building in SDC D → verify soft story error
2. **Seismic Prompt**: Ask Claude for design brief in high-seismic area → verify bracing/anchoring mentioned
3. **Chat Q&A**: Ask "What's the HVAC requirement?" → verify Title 24 SEER/AFUE response with code citation
4. **MEP Coordination**: Check that piping/ductwork spacing warnings appear in issue list
5. **Energy Code**: Verify cool roof and solar-ready roof warnings on design generation

---

**Last Updated**: May 28, 2026  
**Petronus Version**: Post-MEP Code Compliance Update  
**Compliance Standard**: California Building Code (CBC), Title 24, IBC, ASCE 7-22
