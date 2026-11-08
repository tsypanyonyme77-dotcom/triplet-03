import type { FloodZoneData, Frame } from '../recording/types'

export interface DrainState {
  depth: number
  pumpOn: boolean
  /** null in recordings made before rain per street */
  rain: number | null
  blocked: boolean
}

/** What a frame says about one street's drain. */
export function drainState(frame: Frame, zoneId: string): DrainState {
  const row = frame.flood?.find((f) => f[0] === zoneId)
  return { depth: row?.[1] ?? 0, pumpOn: row?.[2] ?? false, rain: row?.[3] ?? null, blocked: row?.[4] ?? false }
}

/** The rain to draw over a street: its own, or for an older recording the city's. */
export function rainOver(frame: Frame, zoneId: string): number {
  return drainState(frame, zoneId).rain ?? frame.rain ?? 0
}

/** "dip-1-4" -> "street 1-4": what people call it. */
export function streetName(zone: FloodZoneData): string {
  return `street ${zone.id.replace(/^dip-/, '')}`
}

/** Where the grate sits: at the low point, against the right-hand kerb (sim metres). */
export function gratePosition(zone: FloodZoneData, inFromKerbM = 0.4): [number, number] {
  const out = zone.road_half_width_m - inFromKerbM
  return [zone.x + Math.sin(zone.heading) * out, zone.y - Math.cos(zone.heading) * out]
}
