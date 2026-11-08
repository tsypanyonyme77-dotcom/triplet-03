import type { FloodZoneData } from '../recording/types'

/** Below the road surface: where a vertex goes when it is dry, so nothing shows. */
export const DRY_Y = -0.05

/**
 * Height of the water surface drawn over the (flat) street, at `s` metres along it from the low point
 * and `across` metres from its centreline, with `depth` metres of water at the low point. The engine's
 * dip is a parabola along the street (twin/engine/flood.py): the water is `depth` deep in the middle and
 * thins out to nothing where the ground comes back up. On the sidewalks the same water is drawn at the
 * same height, so the raised sidewalk hides it until it is deeper than the kerb.
 */
export function waterHeight(zone: FloodZoneData, depth: number, s: number, across: number): number {
  if (depth <= 0 || Math.abs(s) >= zone.half_length_m) return DRY_Y
  if (Math.abs(across) > zone.road_half_width_m + zone.sidewalk_width_m) return DRY_Y
  const h = depth - zone.dip_depth_m * (s / zone.half_length_m) ** 2
  return h > 0.005 ? h : DRY_Y
}

/** Grid of vertices (x along the street, y up, z across) covering the dip and its sidewalks. */
export function waterGrid(zone: FloodZoneData, depth: number, along: number, acrossCount: number): Float32Array {
  const halfWidth = zone.road_half_width_m + zone.sidewalk_width_m
  const out = new Float32Array((along + 1) * (acrossCount + 1) * 3)
  let k = 0
  for (let i = 0; i <= along; i++) {
    const s = -zone.half_length_m + (2 * zone.half_length_m * i) / along
    for (let j = 0; j <= acrossCount; j++) {
      const a = -halfWidth + (2 * halfWidth * j) / acrossCount
      out[k++] = s
      out[k++] = waterHeight(zone, depth, s, a)
      out[k++] = a
    }
  }
  return out
}
