import { describe, expect, it } from 'vitest'
import type { CityMap } from '../recording/types'
import { cctvViews } from './cctv'

const map = {
  roads: { nodes: [{ id: 2, x: 80, y: 0 }, { id: 3, x: 160, y: 0 }, { id: 5, x: 80, y: 80 }], edges: [] },
  cameras: [{ id: 'cam-n2', node: 2, x: 80, y: 0, range_m: 45, looks_toward: [3, 5] }],
} as unknown as CityMap

describe('cctvViews', () => {
  it('gives one view per street a camera looks down, from a pole at the corner', () => {
    const [east, north] = cctvViews(map)
    expect(east.id).toBe('cam-n2>3')
    expect(east.label).toBe('cam-n2, looking down street 2-3')
    expect(east.eye).toEqual([76, 7, 7]) // 4 m back, 7 m to the right (south), on a 7 m pole
    expect(east.look).toEqual([110, 0, -0])
    expect(north.look[2]).toBe(-30)
  })

  it('has none for a recording without cameras', () => {
    expect(cctvViews({ ...map, cameras: undefined })).toEqual([])
  })
})
