// How each building looks: chosen from its id alone, so every load and every viewer shows the same city.

export interface BuildingLook {
  /** wall colour, and whether it is brick (courses drawn) or plaster */
  wall: string
  brick: boolean
  /** window frames and cornices */
  trim: string
  /** metres between window centres along the facade */
  bay: number
  /** window width and height as a share of a bay and a floor */
  windowW: number
  windowH: number
  /** a shop on the ground floor, with its awning colour */
  shop: boolean
  awning: string
  /** boxes on the roof: plant rooms, air conditioning */
  roofUnits: number
  /** a key naming the textures this look needs, shared by buildings that look alike */
  textureKey: string
}

export const FLOOR_M = 3.2
export const GROUND_FLOOR_M = 4.0

const WALLS: { color: string; brick: boolean }[] = [
  { color: '#e8dcc4', brick: false },
  { color: '#d6c2a1', brick: false },
  { color: '#c9d2d8', brick: false },
  { color: '#f0e8dc', brick: false },
  { color: '#a8553f', brick: true },
  { color: '#b96b4a', brick: true },
  { color: '#8c5a46', brick: true },
  { color: '#bfc5b1', brick: false },
]
const TRIMS = ['#f7f4ee', '#5b5148', '#2f3437', '#d8d2c6']
const AWNINGS = ['#c0392b', '#1f6f8b', '#2e8b57', '#d68910', '#6c3483', '#34495e']
const BAYS = [2.6, 3.0, 3.4]
const WINDOWS: [number, number][] = [
  [0.55, 0.55],
  [0.4, 0.62],
  [0.7, 0.5],
]

function hash(text: string, salt: number): number {
  let h = 2166136261 ^ salt
  for (const ch of text) h = Math.imul(h ^ ch.charCodeAt(0), 16777619)
  return h >>> 0
}

const pick = <T,>(list: T[], id: string, salt: number): T => list[hash(id, salt) % list.length]

export function buildingLook(id: string): BuildingLook {
  const wall = pick(WALLS, id, 1)
  const trim = pick(TRIMS, id, 2)
  const [windowW, windowH] = pick(WINDOWS, id, 3)
  const bay = pick(BAYS, id, 4)
  const look = {
    wall: wall.color,
    brick: wall.brick,
    trim,
    bay,
    windowW,
    windowH,
    shop: hash(id, 5) % 3 !== 0,
    awning: pick(AWNINGS, id, 6),
    roofUnits: hash(id, 7) % 3,
  }
  return { ...look, textureKey: `${look.wall}|${look.brick}|${look.trim}|${look.windowW}|${look.windowH}` }
}

/** The wall colour alone (kept for whoever only needs a colour). */
export function facadeColor(id: string): string {
  return buildingLook(id).wall
}
