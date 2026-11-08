import { describe, expect, it } from 'vitest'
import type { BuildingData, Frame } from '../recording/types'
import { hudSnapshot } from './derive'
import { diffSnapshots } from './events'
import { clockText, speedText } from './format'

const frame = (over: Partial<Frame> = {}): Frame => ({ t: 1, cars: [], pedestrians: [], lights: {}, accidents: [], ...over })
const car = (id: string, status: string): Frame['cars'][number] => [id, 0, 0, 0, 0, status]
const unit = (id: string, kind: string, callStatus: string): Frame['cars'][number] => [id, 0, 0, 0, 0, kind, 0, 0, callStatus]
const building = (id: string, x: number, y: number): BuildingData => ({ id, x, y, width: 12, depth: 14, height: 20, street: [1, 2], front: [x, y] })

describe('hudSnapshot', () => {
  it('counts the cars and people, and keeps the emergency vehicles apart', () => {
    const s = hudSnapshot(
      frame({
        cars: [car('car1', 'driving'), car('car2', 'parked'), car('car3', 'driving'), unit('fire1', 'fire', 'idle')],
        pedestrians: [['p1', 0, 0, 0, 1, 'walking'], ['p2', 0, 0, 0, 0, 'calling']],
      }),
    )
    expect([s.carsDriving, s.carsParked, s.pedestrians, s.onThePhone]).toEqual([2, 1, 2, 1])
    expect(s.units).toEqual([{ id: 'fire1', kind: 'fire', state: 'ready' }])
  })

  it.each([
    ['idle', 'ready'],
    ['dispatched', 'on_the_way'],
    ['on_scene', 'working'],
    ['cleaning', 'working'],
    ['returning', 'returning'],
    ['to_hospital', 'returning'],
  ])('reads a unit status %s as %s', (callStatus, state) => {
    expect(hudSnapshot(frame({ cars: [unit('amb1', 'ambulance', callStatus)] })).units[0].state).toBe(state)
  })

  it('lists an accident, and says nobody is helping until a matching unit moves', () => {
    const accidents: Frame['accidents'] = [['acc1', 10, 20, 'car1', 'ped3', 'car_pedestrian']]
    const waiting = hudSnapshot(frame({ accidents, cars: [unit('amb1', 'ambulance', 'idle')] })).incidents[0]
    expect(waiting).toMatchObject({ id: 'acc1', kind: 'pedestrian_hit', title: 'Pedestrian hit', x: 10, y: 20, help: 'waiting' })
    expect(hudSnapshot(frame({ accidents, cars: [unit('amb1', 'ambulance', 'dispatched')] })).incidents[0].help).toBe('on_the_way')
    expect(hudSnapshot(frame({ accidents, cars: [unit('police1', 'police', 'on_scene')] })).incidents[0].help).toBe('working')
    expect(hudSnapshot(frame({ accidents, cars: [unit('fire1', 'fire', 'on_scene')] })).incidents[0].help).toBe('waiting')
  })

  it('shows every burning building as one fire card, placed at the strongest one', () => {
    const buildings = new Map([['bld-01-03', building('bld-01-03', 33, 19)], ['bld-01-01', building('bld-01-01', 19, 19)]])
    const one = hudSnapshot(frame({ fires: [['bld-01-03', 0.5, 'f1']] }), buildings).incidents[0]
    expect(one).toMatchObject({ id: 'fires', kind: 'fire', title: 'Building on fire', x: 33, y: 19, help: 'waiting' })
    const two = hudSnapshot(frame({ fires: [['bld-01-03', 0.4, 'f1'], ['bld-01-01', 1, 'f2']], cars: [unit('fire1', 'fire', 'dispatched')] }), buildings)
    expect(two.incidents).toHaveLength(1)
    expect(two.incidents[0]).toMatchObject({ title: '2 buildings on fire', x: 19, help: 'on_the_way' })
    expect(two.burning).toEqual(['bld-01-01', 'bld-01-03'])
  })

  it('has nothing to show for a quiet city and for recordings made before fires', () => {
    expect(hudSnapshot(frame()).incidents).toEqual([])
    expect(hudSnapshot(frame({ fires: undefined })).burning).toEqual([])
  })
})

describe('diffSnapshots', () => {
  const quiet = hudSnapshot(frame({ cars: [unit('fire1', 'fire', 'idle')] }))
  const burning = (ids: string[], unitState = 'idle') =>
    hudSnapshot(frame({ fires: ids.map((b, i) => [b, 1, `f${i}`] as [string, number, string]), cars: [unit('fire1', 'fire', unitState)] }))

  it('says nothing about what was already there at the first look', () => {
    expect(diffSnapshots(null, burning(['bld-01-03']), 's')).toEqual([])
  })

  it('announces a fire, its spread, and its end', () => {
    expect(diffSnapshots(quiet, burning(['bld-01-03']), 's')[0]).toMatchObject({ icon: 'fire', title: 'Fire!', tone: 'alert' })
    const spread = diffSnapshots(burning(['bld-01-03']), burning(['bld-01-03', 'bld-01-01']), 's')
    expect(spread[0]).toMatchObject({ title: 'The fire is spreading!', text: 'bld-01-01 caught fire' })
    expect(diffSnapshots(burning(['bld-01-03']), quiet, 's')[0]).toMatchObject({ icon: 'check', title: 'Fire is out', tone: 'good' })
  })

  it('announces accidents appearing and clearing', () => {
    const hit = hudSnapshot(frame({ accidents: [['acc1', 0, 0, 'car1', 'p1', 'car_pedestrian']] }))
    expect(diffSnapshots(hudSnapshot(frame()), hit, 's')[0]).toMatchObject({ icon: 'accident', title: 'Pedestrian hit' })
    expect(diffSnapshots(hit, hudSnapshot(frame()), 's')[0]).toMatchObject({ title: 'Pedestrian hit cleared', tone: 'good' })
  })

  it('announces a unit leaving and arriving, once each', () => {
    const go = diffSnapshots(burning(['b']), burning(['b'], 'dispatched'), 's')
    expect(go).toMatchObject([{ icon: 'siren', title: 'Fire truck is on its way' }])
    const here = diffSnapshots(burning(['b'], 'dispatched'), burning(['b'], 'on_scene'), 's')
    expect(here).toMatchObject([{ icon: 'arrived', title: 'Fire truck arrived' }])
    expect(diffSnapshots(burning(['b'], 'dispatched'), burning(['b'], 'dispatched'), 's')).toEqual([])
  })
})

describe('format', () => {
  it('writes simulated time as a clock and a speed as a multiplier', () => {
    expect(clockText(125.4)).toBe('02:05')
    expect(clockText(-3)).toBe('00:00')
    expect(speedText(2)).toBe('2x')
    expect(speedText(0.25)).toBe('0.25x')
  })

})

describe('hudSnapshot with floods', () => {
  it('names floods for what they are', () => {
    const f: Frame = { t: 0, cars: [], pedestrians: [], lights: {}, accidents: [
      ['acc3', 1, 2, 'flood_driver', null, 'flooded_car'], ['acc4', 3, 4, null, 'flood_walker', 'trapped_pedestrian']] }
    const [car, walker] = hudSnapshot(f).incidents
    expect(car).toMatchObject({ kind: 'flood', title: 'Car stuck in a flood', detail: 'flood_driver stalled, driver trapped' })
    expect(walker).toMatchObject({ kind: 'flood', title: 'Pedestrian trapped in a flood', detail: 'flood_walker cannot get out' })
  })
})
