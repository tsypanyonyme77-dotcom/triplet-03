import { describe, expect, it } from 'vitest'
import { walkLamps } from './pedestrianSignal'

describe('walkLamps', () => {
  it('is steady green on walk and red when people must wait', () => {
    expect(walkLamps('walk', 3.3)).toEqual({ red: false, green: true })
    expect(walkLamps('dont_walk', 3.3)).toEqual({ red: true, green: false })
  })

  it('blinks green while people finish crossing', () => {
    expect(walkLamps('flash', 0).green).toBe(true)
    expect(walkLamps('flash', 0.34).green).toBe(false)
    expect(walkLamps('flash', 0.67).green).toBe(true)
    expect(walkLamps('flash', 0.34).red).toBe(false)
  })

  it('shows red for a recording without the signal', () => {
    expect(walkLamps(undefined, 0)).toEqual({ red: true, green: false })
  })
})
