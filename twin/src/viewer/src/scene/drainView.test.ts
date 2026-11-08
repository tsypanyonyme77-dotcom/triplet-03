import { describe, expect, it } from 'vitest'
import type { FloodZoneData, Frame } from '../recording/types'
import { drainState, gratePosition, rainOver, streetName } from './drainView'

const frame = (flood: Frame['flood'], rain?: number): Frame => ({ t: 0, cars: [], pedestrians: [], lights: {}, accidents: [], flood, rain })
const zone: FloodZoneData = {
  id: 'dip-1-4', x: 0, y: 40, heading: Math.PI / 2, half_length_m: 24, dip_depth_m: 0.5,
  road_half_width_m: 8, sidewalk_width_m: 4, kerb_height_m: 0.15,
}

describe('drain view', () => {
  it('reads a street from the frame', () => {
    expect(drainState(frame([['dip-1-4', 0.21, true, 120, true]]), 'dip-1-4')).toEqual({ depth: 0.21, pumpOn: true, rain: 120, blocked: true })
    expect(drainState(frame([]), 'dip-1-4')).toEqual({ depth: 0, pumpOn: false, rain: null, blocked: false })
  })

  it('rains only where it rains, and falls back to the city for older recordings', () => {
    const f = frame([['dip-1-4', 0, false, 0, false], ['dip-2-3', 0.1, false, 120, true]], 120)
    expect(rainOver(f, 'dip-1-4')).toBe(0)
    expect(rainOver(f, 'dip-2-3')).toBe(120)
    expect(rainOver(frame([['dip-2-3', 0.1, false]], 80), 'dip-2-3')).toBe(80)
  })

  it('names the street and puts the grate by its right-hand kerb', () => {
    expect(streetName(zone)).toBe('street 1-4')
    const [x, y] = gratePosition(zone)
    expect(x).toBeCloseTo(7.6) // heading north: the right-hand kerb is east
    expect(y).toBeCloseTo(40)
  })
})
