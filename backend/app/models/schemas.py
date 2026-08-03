from datetime import date

from pydantic import BaseModel, Field, model_validator
from typing import Optional, List, Dict, Any, Literal

# All enums live in constants.py — import and re-export for backward compat
from app.constants import (
    StructuralSystem,
    HVACPreference,
    PriorityType,
    ParkingStrategy,
    BuildingUse,
    HouseArchetype,
    DesignStyle,
)

# ── Site ───────────────────────────────────────────────────────────────────

class LatLon(BaseModel):
    lat: float
    lon: float

class SiteInput(BaseModel):
    address: Optional[str] = None
    latlon: Optional[LatLon] = None
    parcel_polygon: Optional[Dict[str, Any]] = None  # GeoJSON

class SiteContext(BaseModel):
    parcel_polygon: Dict[str, Any]
    buildable_envelope_2d: Dict[str, Any]
    area_sqft: float
    centroid: LatLon
    flood_zone: Optional[str] = None
    flood_flag: bool = False
    seismic_category: str = "D"  # CA default
    wind_speed_mph: float = 85.0
    setbacks: Dict[str, float] = Field(default_factory=lambda: {
        "front": 15, "rear": 20, "left": 5, "right": 5
    })
    hazard_detail: Optional[Dict[str, Any]] = None
    terrain: Optional[Dict[str, Any]] = None

# ── Project Spec ───────────────────────────────────────────────────────────

class ProjectSpec(BaseModel):
    # This preflight currently implements California residential scope only.
    region_country: Literal["US"] = "US"
    region_state: Literal["CA"] = "CA"
    occupancy: Optional[Literal[
        "SingleFamilyResidential", "MultiFamilyResidential"
    ]] = None
    construction_scope: Literal[
        "new_construction", "addition", "alteration"
    ] = "new_construction"
    permit_set: bool = False
    # California code-cycle selection is controlled by the permit application
    # filing date.  With no filing date, use the current 2025 cycle and do not
    # infer grandfathering into an earlier edition.
    permit_application_date: Optional[date] = None
    code_cycle: Literal["2022", "2025"] = "2025"
    jurisdiction_city: Optional[str] = None

    # Site
    site: SiteInput

    # Building type
    building_use: BuildingUse = BuildingUse.multi_family
    # Residential: number of bedrooms (0=studio for ADU, 1–5 for SFR/MF).
    bedrooms: Optional[int] = Field(default=None, ge=0, le=5)
    # Bathrooms: whole number = full bath (toilet+sink+shower/tub), .5 = half bath (toilet+sink only).
    # e.g. 2.5 means two full baths + one half bath.
    bathrooms: Optional[float] = Field(default=None, ge=0.5)
    # Residential archetype hint — used by Claude brief + facade generator.
    # e.g. "craftsman", "contemporary", "farmhouse", "cape_cod", "mediterranean"
    house_archetype: Optional[str] = None

    # Building
    target_gross_area_sqft: Optional[float] = None
    unit_count: Optional[int] = None
    stories: int = Field(default=2, ge=1, le=3)
    floor_to_floor_height_ft: float = 10.0

    # Systems
    structural_system: StructuralSystem = StructuralSystem.wood
    hvac_preference: HVACPreference = HVACPreference.mini_split
    parking_strategy: ParkingStrategy = ParkingStrategy.ignore
    priority: PriorityType = PriorityType.cost
    style: Optional[DesignStyle] = None
    material_overrides: Optional[Dict[str, str]] = None
    # keys: walls, roof, floors, windows, foundation, interior_walls
    # values: "wood"|"concrete"|"brick"|"metal"|"glass"|"stone"|"stucco"|"ai"
    fine_details: Optional[Dict[str, Any]] = None
    # ADU sprinkler applicability depends on the legal requirement for the
    # primary dwelling, not merely whether sprinklers happen to be installed.
    primary_dwelling_sprinkler_requirement: Literal[
        "required", "not_required", "unknown"
    ] = "unknown"
    primary_dwelling_sprinkler_determination_source: Optional[str] = None
    # Deprecated input retained only so older saved projects still deserialize.
    # It must not be used as a legal determination of sprinkler applicability.
    primary_dwelling_sprinklered: Optional[bool] = Field(
        default=None,
        description=(
            "Deprecated compatibility field. Use "
            "primary_dwelling_sprinkler_requirement and its determination source."
        ),
        json_schema_extra={"deprecated": True},
    )

    @model_validator(mode="after")
    def validate_code_cycle_for_filing_date(self) -> "ProjectSpec":
        supported_start = date(2023, 1, 1)
        cycle_boundary = date(2026, 1, 1)
        supported_end = date(2028, 12, 31)
        if self.permit_application_date is None:
            if self.code_cycle != "2025":
                raise ValueError(
                    "code_cycle '2022' requires a permit_application_date "
                    "before 2026-01-01; without a filing date, use the current "
                    "2025 cycle"
                )
            return self

        if not supported_start <= self.permit_application_date <= supported_end:
            raise ValueError(
                "permit_application_date is outside the supported California "
                "code-cycle filing window of 2023-01-01 through 2028-12-31"
            )

        expected_cycle = (
            "2025" if self.permit_application_date >= cycle_boundary else "2022"
        )
        if self.code_cycle != expected_cycle:
            raise ValueError(
                f"permit_application_date {self.permit_application_date.isoformat()} "
                f"requires California code_cycle {expected_cycle!r}"
            )
        return self

    @model_validator(mode="after")
    def align_residential_occupancy(self) -> "ProjectSpec":
        expected = (
            "MultiFamilyResidential"
            if self.building_use == BuildingUse.multi_family
            else "SingleFamilyResidential"
        )
        if self.occupancy is None:
            self.occupancy = expected
        elif self.occupancy != expected:
            raise ValueError(
                f"occupancy {self.occupancy!r} conflicts with building_use "
                f"{self.building_use.value!r}; expected {expected!r}"
            )
        return self

    # Height & limit overrides from the wizard
    max_height_ft: Optional[float] = None
    max_floors: Optional[int] = None
    max_bedrooms: Optional[int] = None
    max_sqft: Optional[float] = None
    # keys: outlets_per_room (int), fire_sprinklers (bool), ev_charging (bool),
    #       exhaust_fans (bool), fire_alarms (bool)

# ── Geometry primitives ────────────────────────────────────────────────────

class Point3D(BaseModel):
    x: float
    y: float
    z: float

class BBox(BaseModel):
    min_x: float
    min_y: float
    min_z: float
    max_x: float
    max_y: float
    max_z: float

class Mesh(BaseModel):
    vertices: List[List[float]]   # [[x,y,z], ...]
    faces: List[List[int]]        # [[i,j,k], ...]
    element_id: str
    element_type: str
    level: int = 0
    color: Optional[str] = None

# ── Building Model ─────────────────────────────────────────────────────────

class Level(BaseModel):
    index: int
    elevation_ft: float
    height_ft: float
    label: str

class Room(BaseModel):
    id: str
    type: str           # bedroom, living, kitchen, bathroom, corridor, stair
    unit_id: Optional[str] = None
    polygon: List[List[float]]   # 2D [[x,y], ...]
    level: int
    area_sqft: float

class Wall(BaseModel):
    id: str
    start: List[float]
    end: List[float]
    height_ft: float
    level: int
    is_exterior: bool = False
    is_shear: bool = False

class Column(BaseModel):
    id: str
    x: float
    y: float
    levels: List[int]

class StructuralMember(BaseModel):
    id: str
    type: str           # column, beam, joist, footing, grade_beam, shear_wall
    start: List[float]  # [x, y, z]
    end: List[float]    # [x, y, z]
    section: str        # e.g. "6x6 DF-L #2", "W10x22", "HSS5x5x1/4"
    material: str       # wood, steel, concrete
    load_kips: float = 0.0
    size_m: float = 0.15
    color: str = "#a855f7"

class MEPElement(BaseModel):
    id: str
    system: str          # plumbing, electrical, hvac
    type: str            # pipe, duct, panel, fixture, etc.
    start: List[float]
    end: Optional[List[float]] = None
    level: int
    diameter_in: Optional[float] = None
    width_in: Optional[float] = None
    height_in: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

class ComplianceIssue(BaseModel):
    id: str
    type: str            # clash, compliance, warning
    severity: str        # error, warning, info
    message: str
    fix_suggestion: str
    elements_involved: List[str] = Field(default_factory=list)
    location: Optional[BBox] = None
    citation: Optional[str] = None

class BuildingModel(BaseModel):
    project_id: str
    spec: ProjectSpec
    site_context: Optional[SiteContext] = None
    levels: List[Level] = Field(default_factory=list)
    massing_options: List[Dict[str, Any]] = Field(default_factory=list)
    chosen_massing_index: int = 0
    rooms: List[Room] = Field(default_factory=list)
    walls: List[Wall] = Field(default_factory=list)
    columns: List[Column] = Field(default_factory=list)
    structural_members: List[StructuralMember] = Field(default_factory=list)
    mep_elements: List[MEPElement] = Field(default_factory=list)
    meshes: List[Dict[str, Any]] = Field(default_factory=list)
    neighbor_style: Optional[Dict[str, Any]] = None
    design_brief: Optional[Dict[str, Any]] = None
    issues: List[ComplianceIssue] = Field(default_factory=list)
    generation_log: List[str] = Field(default_factory=list)
    # Machine-readable audit result: counts, checked rules, code cycle, and
    # permit-review limitations.  This prevents "no issues" from being
    # mistaken for a stamped construction-document approval.
    compliance_summary: Dict[str, Any] = Field(default_factory=dict)

# ── API response models ────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str
    spec: ProjectSpec

class ProjectResponse(BaseModel):
    id: str
    name: str
    status: str
    spec: ProjectSpec
    building_model: Optional[BuildingModel] = None

class GenerateRequest(BaseModel):
    project_id: str
    massing_choice: Optional[int] = Field(default=None, ge=0, le=2)  # 0=A,1=B,2=C

class JobStatus(BaseModel):
    job_id: str
    status: str           # pending, running, done, failed
    progress: int         # 0-100
    current_step: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
