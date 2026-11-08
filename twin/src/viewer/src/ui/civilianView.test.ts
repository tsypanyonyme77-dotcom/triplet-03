import { describe, expect, it } from 'vitest'
import type { Agent } from '../api/twinApi'
import { ago, headingAgents, isHeading, percent, topTraits } from './civilianView'

const place = (name: string) => ({ id: name, name, category: 'cafe', x: 0, y: 0 })

function agent(over: Partial<Agent> = {}): Agent {
  return {
    id: 'ped1', kind: 'pedestrian', status: 'walking', label: 'worker', role: 'worker', traits: {},
    home: null, duty: null, at: null, destination: place('Cafe 2'), decided_at_s: 5, probability: 0.4,
    alternatives: [], ...over,
  }
}

describe('isHeading', () => {
  it('is true for people and cars on their way', () => {
    for (const status of ['walking', 'waiting']) expect(isHeading(agent({ status }))).toBe(true)
    for (const status of ['driving', 'unparked', 'parking']) expect(isHeading(agent({ kind: 'car', status }))).toBe(true)
  })

  it('is false for the resting, the undecided, the injured and the crashed', () => {
    expect(isHeading(agent({ status: 'arrived' }))).toBe(false)
    expect(isHeading(agent({ kind: 'car', status: 'parked' }))).toBe(false)
    expect(isHeading(agent({ destination: null }))).toBe(false)
    expect(isHeading(agent({ status: 'injured' }))).toBe(false)
    expect(isHeading(agent({ kind: 'car', status: 'crashed' }))).toBe(false)
  })
})

describe('headingAgents', () => {
  it('keeps only those on the way, newest decision first, ids in natural order', () => {
    const list = [
      agent({ id: 'ped10', decided_at_s: 5 }),
      agent({ id: 'ped2', decided_at_s: 5 }),
      agent({ id: 'car1', kind: 'car', status: 'parked', decided_at_s: 8 }),
      agent({ id: 'ped4', destination: null, decided_at_s: null }),
      agent({ id: 'ped3', decided_at_s: 9 }),
    ]
    expect(headingAgents(list).map((a) => a.id)).toEqual(['ped3', 'ped2', 'ped10'])
  })

  it('does not change the list it was given', () => {
    const list = [agent({ id: 'b', decided_at_s: 1 }), agent({ id: 'a', decided_at_s: 2, status: 'arrived' })]
    headingAgents(list)
    expect(list.map((a) => a.id)).toEqual(['b', 'a'])
  })
})

describe('ago', () => {
  it('counts simulated seconds, then minutes', () => {
    expect(ago(10, 9)).toBe('just now')
    expect(ago(40, 10)).toBe('30 s ago')
    expect(ago(300, 0)).toBe('5 min ago')
    expect(ago(5, null)).toBe('not yet')
    expect(ago(5, 8)).toBe('just now')
  })
})

describe('topTraits and percent', () => {
  it('ranks the traits and rounds a probability', () => {
    expect(topTraits({ a: 0.2, b: 0.9, c: 0.5 }, 2)).toEqual([['b', 0.9], ['c', 0.5]])
    expect(percent(0.227)).toBe('23%')
    expect(percent(null)).toBe('')
  })
})
