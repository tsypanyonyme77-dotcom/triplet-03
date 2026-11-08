import { describe, expect, it } from 'vitest'
import { buildingLook, facadeColor } from './buildingStyle'

const ids = Array.from({ length: 24 }, (_, i) => `bld-0${1 + (i % 2)}-${String(i + 1).padStart(2, '0')}`)

describe('buildingLook', () => {
  it('is the same for the same building, whenever it is asked', () => {
    expect(buildingLook('bld-01-03')).toEqual(buildingLook('bld-01-03'))
    expect(facadeColor('bld-01-03')).toBe(buildingLook('bld-01-03').wall)
  })

  it('varies walls, shops and roofs across a city', () => {
    const looks = ids.map(buildingLook)
    expect(new Set(looks.map((l) => l.wall)).size).toBeGreaterThan(3)
    expect(looks.some((l) => l.shop) && looks.some((l) => !l.shop)).toBe(true)
    expect(looks.some((l) => l.brick) && looks.some((l) => !l.brick)).toBe(true)
    expect(new Set(looks.map((l) => l.roofUnits)).size).toBeGreaterThan(1)
  })
})
