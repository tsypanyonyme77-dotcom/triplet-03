import { describe, expect, it } from 'vitest'
import { personLook } from './personLook'

describe('personLook', () => {
  const ids = Array.from({ length: 200 }, (_, i) => `ped${i}`)

  it('is the same for the same person', () => {
    expect(personLook('ped7')).toEqual(personLook('ped7'))
  })

  it('mixes models, outfits and heights across a crowd', () => {
    const looks = ids.map(personLook)
    expect(new Set(looks.map((l) => l.model.url)).size).toBe(2)
    expect(new Set(looks.map((l) => l.outfit)).size).toBeGreaterThan(8)
    expect(Math.min(...looks.map((l) => l.height))).toBeGreaterThanOrEqual(0.9)
    expect(Math.max(...looks.map((l) => l.height))).toBeLessThanOrEqual(1.08)
  })
})
