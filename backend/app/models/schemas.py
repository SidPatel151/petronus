from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from enum import Enum

# ── Enums ──────────────────────────────────────────────────────────────────

class StructuralSystem(str, Enum):
    wood = "wood"
    steel = "steel"
    concrete = "concrete"

class HVACPreference(str, Enum):
    mini_split = "mini_split"
    rooftop = "rooftop"

class PriorityType(str, Enum):
    speed = "speed"
    cost = "cost"
    daylight = "daylight"

class ParkingStrategy(str, Enum):
    ignore = "ignore"
    surface = "surface"
    podium = "podium"

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
    # Fixed for demo
    region_country: str = "US"
    region_state: str = "CA"
    occupancy: str = "MultiFamilyResidential"
    permit_set: bool = False

    # Site
    site: SiteInput

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

class ComplianceIssue(BaseModel):
    id: str
    type: str            # clash, compliance, warning
    severity: str        # error, warning, info
    message: str
    fix_suggestion: str
    elements_involved: List[str] = []
    location: Optional[BBox] = None
    citation: Optional[str] = None

class BuildingModel(BaseModel):
    project_id: str
    spec: ProjectSpec
    site_context: Optional[SiteContext] = None
    levels: List[Level] = []
    massing_options: List[Dict[str, Any]] = []
    chosen_massing_index: int = 0
    rooms: List[Room] = []
    walls: List[Wall] = []
    columns: List[Column] = []
    mep_elements: List[MEPElement] = []
    meshes: List[Dict[str, Any]] = []
    neighbor_style: Optional[Dict[str, Any]] = None
    issues: List[ComplianceIssue] = []
    generation_log: List[str] = []

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
    massing_choice: Optional[int] = None  # 0=A,1=B,2=C

class JobStatus(BaseModel):
    job_id: str
    status: str           # pending, running, done, failed
    progress: int         # 0-100
    current_step: str
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None