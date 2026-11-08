import { describe, expect, it } from 'vitest'
import { wallFaces } from './wallFaces'

const box = { x: 20, y: 30, width: 13, depth: 14, height: 11 }

describe('wallFaces', () => {
  it('gives one sign per wall, just outside it, facing out', () => {
    const faces = Object.fromEntries(wallFaces(box).map((f) => [f.side, f]))
    expect(Object.keys(faces).sort()).toEqual(['east', 'north', 'south', 'west'])
    // sim y north is world -z: the north wall is at the smaller z
    expect(faces.east.position[0]).toBeGreaterThan(20 + 13 / 2)
    expect(faces.west.position[0]).toBeLessThan(20 - 13 / 2)
    expect(faces.north.position[2]).toBeLessThan(-30 - 14 / 2)
    expect(faces.south.position[2]).toBeGreaterThan(-30 + 14 / 2)
    // a plane faces +z; turning it by theta about y points its front along (sin theta, 0, cos theta)
    for (const f of Object.values(faces)) {
      const out: [number, number] = [Math.sin(f.rotationY), Math.cos(f.rotationY)]
      const away: [number, number] = [f.position[0] - 20, f.position[2] + 30]
      expect(out[0] * away[0] + out[1] * away[1]).toBeGreaterThan(0)
    }
  })

  it('keeps every sign inside its wall and below the roof', () => {
    for (const f of wallFaces(box)) {
      const wall = f.side === 'east' || f.side === 'west' ? box.depth : box.width
      expect(f.width).toBeLessThanOrEqual(wall)
      expect(f.position[1] + f.height / 2).toBeLessThan(box.height)
      expect(f.position[1] - f.height / 2).toBeGreaterThan(0)
      expect(f.width / f.height).toBeCloseTo(4)
    }
  })

  it('shrinks the sign on a small or low building instead of overflowing', () => {
    for (const f of wallFaces({ x: 0, y: 0, width: 4, depth: 5, height: 3 })) {
      expect(f.position[1] + f.height / 2).toBeLessThan(3)
      expect(f.width).toBeLessThanOrEqual(5)
    }
  })
})
