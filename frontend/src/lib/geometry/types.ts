// Semantic building model — the parametric representation Claude generates.
// The geometry engine reads this and produces Three.js geometry.
// Both AI edits and human drag operations write to this model.

export type WallMaterial =
  | 'wood_siding' | 'brick' | 'stucco' | 'concrete' | 'stone'
  | 'fiber_cement' | 'metal_panel' | 'glass_curtain'

export type OpeningType = 'window' | 'door' | 'garage' | 'slider' | 'picture_window'
export type OpeningStyle =
  | 'double_hung' | 'casement' | 'bay_3panel' | 'strip_horizontal'
  | 'circle_transom' | 'arched' | 'picture' | 'sliding_glass'
  | 'french' | 'paneled' | 'victorian_paneled'

export type RoofType = 'flat' | 'gabled' | 'hipped' | 'shed' | 'mansard' | 'gambrel'
export type RoofMaterial = 'asphalt_shingle' | 'slate' | 'metal_standing_seam' | 'clay_tile' | 'flat_membrane'

export interface SemanticWall {
  id: string
  floor: number
  /** XZ plane — Y is up */
  start: [number, number]
  end: [number, number]
  height_m: number
  thickness_m: number
  exterior: boolean
  material: WallMaterial
}

export interface SemanticOpening {
  id: string
  wall_id: string
  type: OpeningType
  style: OpeningStyle
  /** Distance from wall start point along wall direction */
  offset_m: number
  width_m: number
  height_m: number
  /** Height of sill from floor */
  sill_m: number
}

export interface SemanticFloor {
  level: number
  height_m: number
}

export interface SemanticRoof {
  type: RoofType
  pitch_12: number
  material: RoofMaterial
  overhang_m: number
  /** Flat roofs get a parapet instead */
  parapet_height_m?: number
}

export interface SemanticTrim {
  cornice_height_m: number
  band_height_m: number
  band_at_floor: number[]  // which floor levels get a band
  trim_color: string
}

export interface SemanticMaterials {
  wall_body: WallMaterial
  trim_color: string        // hex
  window_frame_color: string // hex
  door_color: string        // hex
  roof: RoofMaterial
}

export interface SemanticPorch {
  type: 'entry' | 'wraparound' | 'rear_deck' | 'balcony'
  floor: number
  depth_m: number
  width_m: number
  /** Which wall face it's on */
  wall_id: string
}

export interface SemanticBuildingModel {
  /** Human-readable style intent Claude chose */
  style_intent: string
  archetype_id: string

  footprint: {
    width_m: number
    depth_m: number
    shape: 'rectangle' | 'narrow_lot' | 'l_shape' | 'u_shape' | 'sculpted'
    offset_x?: number
    offset_z?: number
  }

  floors: SemanticFloor[]
  walls: SemanticWall[]
  openings: SemanticOpening[]
  porches: SemanticPorch[]
  roof: SemanticRoof
  trim: SemanticTrim
  materials: SemanticMaterials

  /** Used to feed MEP/compliance back-compat */
  legacy_meshes?: any[]
}
