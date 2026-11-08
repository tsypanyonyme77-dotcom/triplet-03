import type { CityMap, RoadNode } from '../recording/types'

// Cross-section of a street, measured from the centreline; exported by the sim
// (app/street_profile.py) so the models sit exactly where the engines put them.
export interface StreetProfile {
  asphaltHalfWidth: number // driving lanes + parking lane, up to the kerb
  sidewalkOuter: number // where the block (grass, buildings) starts
}

export function streetProfile(map: CityMap): StreetProfile {
  return {
    asphaltHalfWidth: map.profile.kerb_m,
    sidewalkOuter: map.profile.kerb_m + map.profile.sidewalk_width_m,
  }
}

export interface Street {
  a: RoadNode
  b: RoadNode
}

/** One entry per undirected street (the graph stores both directions). */
export function streets(map: CityMap): Street[] {
  const byId = new Map(map.roads.nodes.map((n) => [n.id, n]))
  const seen = new Set<string>()
  const out: Street[] = []
  for (const e of map.roads.edges) {
    const key = e.u < e.v ? `${e.u}-${e.v}` : `${e.v}-${e.u}`
    if (seen.has(key)) continue
    seen.add(key)
    const a = byId.get(e.u)
    const b = byId.get(e.v)
    if (a && b) out.push({ a, b })
  }
  return out
}

export interface BlockRect {
  minX: number
  maxX: number
  minY: number
  maxY: number
}

/** City blocks of a rectangular street grid: the cells between neighbouring street lines. */
export function blocks(map: CityMap): BlockRect[] {
  const xs = [...new Set(map.roads.nodes.map((n) => n.x))].sort((p, q) => p - q)
  const ys = [...new Set(map.roads.nodes.map((n) => n.y))].sort((p, q) => p - q)
  const out: BlockRect[] = []
  for (let i = 0; i + 1 < xs.length; i++) {
    for (let j = 0; j + 1 < ys.length; j++) {
      out.push({ minX: xs[i], maxX: xs[i + 1], minY: ys[j], maxY: ys[j + 1] })
    }
  }
  return out
}

export function bounds(map: CityMap): BlockRect {
  const xs = map.roads.nodes.map((n) => n.x)
  const ys = map.roads.nodes.map((n) => n.y)
  return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) }
}
