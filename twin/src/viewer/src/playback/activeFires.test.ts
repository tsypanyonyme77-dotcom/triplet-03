import { describe, expect, it } from 'vitest'
import type { Frame } from '../recording/types'
import { activeFires } from './activeFires'

const frame = (fires?: Frame['fires']): Frame => ({ t: 1, cars: [], pedestrians: [], lights: {}, accidents: [], fires })

describe('activeFires', () => {
  it('lists each burning building with its strength', () => {
    expect(activeFires(frame([['bld-01-03', 0.5, 'fire-0001'], ['bld-01-01', 1, 'fire-0002']]))).toEqual([
      { buildingId: 'bld-01-03', strength: 0.5 },
      { buildingId: 'bld-01-01', strength: 1 },
    ])
  })

  it('is empty when nothing burns and for recordings made before fires', () => {
    expect(activeFires(frame([]))).toEqual([])
    expect(activeFires(frame(undefined))).toEqual([])
  })
})
