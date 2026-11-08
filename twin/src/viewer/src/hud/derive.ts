import type { BuildingData, EntityTuple, Frame } from '../recording/types'

export type UnitKind = 'ambulance' | 'police' | 'fire'
/** What an emergency vehicle is doing, in words a person would use. */
export type UnitState = 'ready' | 'on_the_way' | 'working' | 'returning'
/** How help is going for an incident. */
export type Help = 'waiting' | 'on_the_way' | 'working'
export type IncidentKind = 'fire' | 'pedestrian_hit' | 'car_crash' | 'flood'

export interface UnitInfo {
  id: string
  kind: UnitKind
  state: UnitState
}

export interface Incident {
  /** stable while it lasts: an accident's id, or `fires` for every burning building together */
  id: string
  kind: IncidentKind
  title: string
  detail: string
  /** where the camera goes when the card is clicked (sim metres) */
  x: number
  y: number
  help: Help
}

export interface HudSnapshot {
  carsDriving: number
  carsParked: number
  pedestrians: number
  onThePhone: number
  units: UnitInfo[]
  incidents: Incident[]
  /** ids of the burning buildings, for noticing a fire that spreads or goes out */
  burning: string[]
}

const UNIT_KINDS: readonly string[] = ['ambulance', 'police', 'fire']
const UNIT_STATE: Record<string, UnitState> = {
  idle: 'ready',
  dispatched: 'on_the_way',
  on_scene: 'working',
  cleaning: 'working',
  to_hospital: 'returning',
  returning: 'returning',
}
/** Who can help with what. A crash needs the police as much as an ambulance. */
const HELPERS: Record<IncidentKind, UnitKind[]> = {
  fire: ['fire'],
  pedestrian_hit: ['ambulance', 'police'],
  car_crash: ['ambulance', 'police'],
  flood: ['fire', 'police'],
}

const isUnit = (row: EntityTuple): boolean => UNIT_KINDS.includes(row[5])

export function unitsOf(frame: Frame): UnitInfo[] {
  return frame.cars
    .filter(isUnit)
    .map((row) => ({ id: row[0], kind: row[5] as UnitKind, state: UNIT_STATE[row[8] ?? 'idle'] ?? 'ready' }))
}

function helpFor(kind: IncidentKind, units: UnitInfo[]): Help {
  const helpers = units.filter((u) => HELPERS[kind].includes(u.kind))
  if (helpers.some((u) => u.state === 'working')) return 'working'
  if (helpers.some((u) => u.state === 'on_the_way')) return 'on_the_way'
  return 'waiting'
}

/** Everything the overlay shows about one frame. `buildings` places fires on the map. */
export function hudSnapshot(frame: Frame, buildings: ReadonlyMap<string, BuildingData> = new Map()): HudSnapshot {
  const units = unitsOf(frame)
  const incidents: Incident[] = frame.accidents.map(([id, x, y, carId, otherId, kind]) => {
    if (kind === 'flooded_car') return { id, kind: 'flood', title: 'Car stuck in a flood', detail: `${carId} stalled, driver trapped`, x, y, help: helpFor('flood', units) }
    if (kind === 'trapped_pedestrian') return { id, kind: 'flood', title: 'Pedestrian trapped in a flood', detail: `${otherId} cannot get out`, x, y, help: helpFor('flood', units) }
    if (kind === 'car_car') return { id, kind: 'car_crash', title: 'Car crash', detail: `${carId} hit ${otherId}`, x, y, help: helpFor('car_crash', units) }
    return { id, kind: 'pedestrian_hit', title: 'Pedestrian hit', detail: `${carId} hit ${otherId}`, x, y, help: helpFor('pedestrian_hit', units) }
  })
  const fires = frame.fires ?? []
  if (fires.length > 0) {
    const [first] = [...fires].sort((a, b) => b[1] - a[1])
    const where = buildings.get(first[0])
    const strongest = Math.round(first[1] * 100)
    incidents.push({
      id: 'fires',
      kind: 'fire',
      title: fires.length === 1 ? 'Building on fire' : `${fires.length} buildings on fire`,
      detail: fires.length === 1 ? `${first[0]}, ${strongest}% strong` : `${first[0]} and ${fires.length - 1} more, up to ${strongest}%`,
      x: where?.x ?? 0,
      y: where?.y ?? 0,
      help: helpFor('fire', units),
    })
  }
  return {
    carsDriving: frame.cars.filter((r) => !isUnit(r) && r[5] === 'driving').length,
    carsParked: frame.cars.filter((r) => !isUnit(r) && r[5] === 'parked').length,
    pedestrians: frame.pedestrians.length,
    onThePhone: frame.pedestrians.filter((r) => r[5] === 'calling').length + (frame.calls?.filter((c) => c[1] === 'driver').length ?? 0),
    units,
    incidents,
    burning: fires.map((f) => f[0]).sort(),
  }
}
