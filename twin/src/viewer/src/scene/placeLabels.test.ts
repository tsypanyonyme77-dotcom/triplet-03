import { describe, expect, it } from 'vitest'
import type { Agent } from '../api/twinApi'
import type { PlaceData } from '../recording/types'
import { NO_HIGHLIGHT, highlightOf, roleOf } from './placeLabels'

const places: PlaceData[] = [
  { id: 'h1', name: 'Residence 1', category: 'home', x: 0, y: 0 },
  { id: 'h2', name: 'Residence 2', category: 'home', x: 0, y: 0 },
  { id: 'h3', name: 'Residence 3', category: 'home', x: 0, y: 0 },
  { id: 'c1', name: 'Cafe 1', category: 'cafe', x: 0, y: 0 },
  { id: 'o1', name: 'Office 1', category: 'office', x: 0, y: 0 },
]

const ref = (id: string) => ({ id, name: id, category: 'x' })

describe('highlightOf and roleOf', () => {
  it('reads the places off the selected person', () => {
    const agent = { destination: { ...ref('c1'), x: 0, y: 0 }, home: ref('h1'), duty: null } as unknown as Agent
    const hl = highlightOf(agent)
    expect(hl).toEqual({ destination: 'c1', home: 'h1', duty: null })
    expect(places.map((p) => roleOf(p, hl))).toEqual(['home', 'plain', 'plain', 'destination', 'plain'])
    expect(highlightOf(undefined)).toBe(NO_HIGHLIGHT)
  })
})
