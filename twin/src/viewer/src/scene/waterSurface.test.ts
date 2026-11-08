import { describe, expect, it } from 'vitest'
import type { FloodZoneData } from '../recording/types'
import { DRY_Y, waterGrid, waterHeight } from './waterSurface'

const zone: FloodZoneData = {
  id: 'dip-2-3', x: 118, y: 0, heading: 0, half_length_m: 24, dip_depth_m: 0.5,
  road_half_width_m: 8, sidewalk_width_m: 4, kerb_height_m: 0.15,
}

describe('waterHeight', () => {
  it('is the depth at the low point and thins out along the parabolic dip', () => {
    expect(waterHeight(zone, 0.4, 0, 0)).toBeCloseTo(0.4)
    expect(waterHeight(zone, 0.4, 12, 2)).toBeCloseTo(0.4 - 0.5 * 0.25)
    expect(waterHeight(zone, 0.4, 23, 0)).toBe(DRY_Y) // the ground is above the water there
  })

  it('stays out of sight when dry or outside the street', () => {
    expect(waterHeight(zone, 0, 0, 0)).toBe(DRY_Y)
    expect(waterHeight(zone, 0.4, 30, 0)).toBe(DRY_Y)
    expect(waterHeight(zone, 0.4, 0, 13)).toBe(DRY_Y)
  })
})

describe('waterGrid', () => {
  it('covers the dip and both sidewalks with (along, up, across) vertices', () => {
    const grid = waterGrid(zone, 0.3, 4, 2)
    expect(grid.length).toBe(5 * 3 * 3)
    expect([grid[0], grid[2]]).toEqual([-24, -12])                       // first corner
    expect(grid[(2 * 3 + 1) * 3 + 1]).toBeCloseTo(0.3)                    // the middle vertex
  })
})
