// Shape of public/recording.json, written by sim/record.py.

/**
 * [id, x, y, heading_rad, speed_ms, status] in simulation metres (x east, y north).
 * Vehicles append [steer_rad (front wheels, + = left), accel_ms2]; older recordings lack them.
 * Emergency vehicles have their kind (ambulance | police | fire) as status and append their
 * call status (idle | dispatched | cleaning | returning).
 */
export type EntityTuple = [string, number, number, number, number, string, number?, number?, string?]

export interface Frame {
  t: number
  cars: EntityTuple[]
  pedestrians: EntityTuple[]
  /** light node id -> upstream node id -> "green" | "yellow" | "red" */
  lights: Record<string, Record<string, string>>
  /** light node id -> pedestrian signal: "walk" | "flash" | "dont_walk"; missing in older recordings */
  walk?: Record<string, string>
  /** people on the phone to the emergency number: [reporter id, 'pedestrian' | 'driver', call id];
   * missing in older recordings */
  calls?: [string, 'pedestrian' | 'driver', string][]
  /** active (not yet cleared) accidents: [id, x, y, car_id (null for a pedestrian trapped in a flood),
   * other party id (pedestrian or car; null for a car stalled in a flood), kind] */
  accidents: [string, number, number, string | null, string | null, AccidentKind][]
  /** burning buildings: [building id, strength 0..1, fire id]; missing in recordings made before fires */
  fires?: [string, number, string][]
  /** rain in mm/h; missing in recordings made before rain */
  rain?: number
  /** per flood zone: [zone id, depth at its low point (m), pump on, rain there (mm/h), drain blocked];
   * missing in recordings made before floods, the last two before rain per street */
  flood?: [string, number, boolean, number?, boolean?][]
}

export type AccidentKind = 'car_pedestrian' | 'car_car' | 'flooded_car' | 'trapped_pedestrian'

/** A low point of a street where rain collects (twin/engine/flood.py): a parabolic dip along the street. */
export interface FloodZoneData {
  id: string
  /** the low point (sim metres) and the street's direction */
  x: number
  y: number
  heading: number
  /** the dip reaches this far either side of the low point, and is this deep in the middle */
  half_length_m: number
  dip_depth_m: number
  /** centreline to kerb, and the sidewalk beyond it */
  road_half_width_m: number
  sidewalk_width_m: number
  kerb_height_m: number
}

export interface RoadNode {
  id: number
  x: number
  y: number
  has_light: boolean
}

export interface RoadEdge {
  u: number
  v: number
  length: number
  lanes: number
}

export interface ParkingSpot {
  id: string
  /** centre of the bay (sim metres) and the direction of travel of its lane */
  x: number
  y: number
  heading: number
  /** bay size along the kerb and across the parking lane (m); missing in older recordings */
  length?: number
  width?: number
}

export interface StreetProfileData {
  driving_outer_m: number
  parking_lane_m: number
  kerb_m: number
  sidewalk_width_m: number
}

export interface CrosswalkData {
  id: string
  /** both ends, on the sidewalk centrelines (sim metres) */
  a: [number, number]
  b: [number, number]
  width: number
  signalised: boolean
  /** the junction it belongs to; missing in older recordings */
  node?: number
}

export interface StopLineData {
  approach: [number, number]
  x: number
  y: number
  heading: number
  length: number
}

/** Footprint every vehicle occupies in the sim (m); its front bumper is the recorded x, y. */
export interface VehicleBody {
  length: number
  width: number
}

export type StationKind = 'hospital' | 'police_station' | 'fire_station'

/** A station and the bays of its vehicles (simulation/app/stations.py). */
export interface StationData {
  id: string
  kind: StationKind
  unit_kind: 'ambulance' | 'police' | 'fire'
  label: string
  bays: { spot_id: string; x: number; y: number; heading: number }[]
  /** point on the building line behind the sidewalk, in front of the first bay (sim metres) */
  front: [number, number]
  /** sim heading from the building toward the street */
  facing: number
}

/** A building behind the sidewalks (twin/engine/buildings.py): footprint centre and size in sim metres. */
export interface BuildingData {
  id: string
  x: number
  y: number
  width: number
  depth: number
  height: number
  /** the street it faces, as road node ids */
  street: [number, number]
  /** where people see it from, on its street face */
  front: [number, number]
}

/** A named destination (home, cafe, clinic...) the road users choose from. */
export interface PlaceData {
  id: string
  name: string
  category: string
  x: number
  y: number
  /** the 3D building this place is (its name is written on the walls); missing in older recordings */
  building_id?: string | null
}

export interface CityMap {
  lane_width_m: number
  /** missing in recordings made before models were fitted to it */
  vehicle?: VehicleBody
  roads: { nodes: RoadNode[]; edges: RoadEdge[] }
  parking: ParkingSpot[]
  profile: StreetProfileData
  crosswalks: CrosswalkData[]
  stop_lines: StopLineData[]
  /** missing in recordings made before stations */
  stations?: StationData[]
  /** missing in recordings made before the engine knew its buildings; the viewer then draws its own ring */
  buildings?: BuildingData[]
  /** missing in recordings made before places were named */
  places?: PlaceData[]
  /** missing in recordings made before floods */
  flood_zones?: FloodZoneData[]
  /** the traffic (CCTV) cameras; missing in recordings made before they were listed */
  cameras?: CameraData[]
}

export interface CameraData {
  id: string
  /** its junction */
  node: number
  x: number
  y: number
  range_m: number
  /** the neighbouring junctions: it looks down the streets to them */
  looks_toward: number[]
}

export interface Recording {
  dt: number
  map: CityMap
  frames: Frame[]
}
