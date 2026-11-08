import { describe, expect, it } from 'vitest'
import type { Frame } from '../recording/types'
import { frameAt, frameIndex } from './frameAt'

const frames = (...ts: number[]) => ts.map((t) => ({ t }) as Frame)
const DT = 0.1

describe('frameIndex', () => {
  it('is the plain estimate when frames are evenly spaced', () => {
    const even = frames(0.1, 0.2, 0.3, 0.4)
    expect(frameIndex(even, DT, 0.25)).toBeCloseTo(1.5)
    expect(frameIndex(even, DT, 0.05)).toBeCloseTo(-0.5)
    expect(frameIndex(even, DT, 0.6)).toBeCloseTo(5)
  })

  it('stays on the right frames after a gap in a live stream', () => {
    const gap = frames(1.0, 1.1, 1.2, 9.0, 9.1, 9.2)
    expect(frameAt(gap, DT, 9.1).t).toBe(9.1) // the estimate would run past the end and stick there
    expect(frameIndex(gap, DT, 9.05)).toBeCloseTo(3.5)
    expect(frameAt(gap, DT, 1.1).t).toBe(1.1)
    expect(frameIndex(gap, DT, 5.1)).toBeCloseTo(2.5) // inside the gap
    expect(frameAt(gap, DT, 100).t).toBe(9.2)
  })

  it('handles the empty and single frame cases', () => {
    expect(frameIndex([], DT, 0.3)).toBeCloseTo(2)
    expect(frameIndex(frames(5), DT, 5)).toBe(0)
    expect(frameIndex(frames(5), DT, 5.05)).toBeCloseTo(0.5)
  })
})
