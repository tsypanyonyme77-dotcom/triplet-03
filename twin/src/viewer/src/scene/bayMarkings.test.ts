import { describe, expect, it } from 'vitest'
import { bayLines, LINE_M } from './bayMarkings'

describe('bayLines', () => {
  const lines = bayLines(5.5, 3.0)

  it('paints the lane-side edge and both ends, leaving the kerb side open', () => {
    expect(lines).toHaveLength(3)
    const [lane, ...ends] = lines
    // along the bay, on the side of the driving lane (local -z)
    expect(lane).toEqual({ x: 0, z: -1.5 + LINE_M / 2, along: 5.5, across: LINE_M })
    // across the bay at each end, from the lane edge to the kerb
    expect(ends).toEqual([
      { x: -2.75 + LINE_M / 2, z: 0, along: LINE_M, across: 3.0 },
      { x: 2.75 - LINE_M / 2, z: 0, along: LINE_M, across: 3.0 },
    ])
  })

  it('keeps every line inside the bay', () => {
    for (const l of lines) {
      expect(Math.abs(l.x) + l.along / 2).toBeLessThanOrEqual(2.75 + 1e-9)
      expect(Math.abs(l.z) + l.across / 2).toBeLessThanOrEqual(1.5 + 1e-9)
    }
  })
})
