import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LiveStream, type LiveState } from './liveStream'

class FakeSource {
  static all: FakeSource[] = []
  closed = false
  onerror: (() => void) | null = null
  private handlers = new Map<string, (e: { data: string }) => void>()

  constructor() {
    FakeSource.all.push(this)
  }
  addEventListener(event: string, handler: (e: { data: string }) => void) {
    this.handlers.set(event, handler)
  }
  close() {
    this.closed = true
  }
  send(event: string, data: unknown) {
    this.handlers.get(event)?.({ data: typeof data === 'string' ? data : JSON.stringify(data) })
  }
}

const latest = () => FakeSource.all[FakeSource.all.length - 1]
const frame = (t: number) => ({ t, cars: [], pedestrians: [], lights: {}, calls: [], accidents: [] })
const settle = () => vi.advanceTimersByTimeAsync(0)

describe('LiveStream', () => {
  let states: LiveState[]
  let run: { instance: string; run_id: number; scenario: string }
  let fetchMap: ReturnType<typeof vi.fn>
  let stream: LiveStream
  const last = () => states[states.length - 1]
  const ready = () => {
    const state = last()
    if (state.status !== 'ready') throw new Error(`expected ready, got ${state.status}`)
    return state
  }

  beforeEach(() => {
    vi.useFakeTimers()
    FakeSource.all = []
    states = []
    run = { instance: 'a', run_id: 1, scenario: 'ped-hit' }
    fetchMap = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ dt: 0.1, map: {}, ...run }) }))
    vi.stubGlobal('EventSource', FakeSource)
    vi.stubGlobal('fetch', fetchMap)
    stream = new LiveStream((s) => states.push(s))
    stream.start()
  })

  afterEach(() => {
    stream.stop()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  const connect = async () => {
    latest().send('hello', run)
    await settle()
  }

  it('loads the map on hello and appends frames in time order', async () => {
    latest().send('hello', run)
    latest().send('frame', frame(0.1)) // while the map loads: kept
    await settle()
    latest().send('frame', frame(0.2))
    latest().send('frame', frame(0.2)) // not forward: ignored
    expect(ready().connected).toBe(true)
    expect(ready().recording.frames.map((f) => f.t)).toEqual([0.1, 0.2])
  })

  it('keeps the scene and the same recording through a dropped stream of the same run', async () => {
    await connect()
    latest().send('frame', frame(1))
    const before = ready().recording

    latest().onerror?.()
    expect(ready().connected).toBe(false)
    expect(ready().recording).toBe(before)

    await vi.advanceTimersByTimeAsync(1_000)
    expect(FakeSource.all).toHaveLength(2)
    await connect()
    latest().send('frame', frame(9))

    expect(ready().connected).toBe(true)
    expect(ready().recording).toBe(before) // no reload, no new scene
    expect(fetchMap).toHaveBeenCalledTimes(1)
    expect(before.frames.map((f) => f.t)).toEqual([1, 9]) // a gap, handled by frameIndex
  })

  it('starts a new recording when the Twin restarted, even with the same run id and an earlier time', async () => {
    await connect()
    latest().send('frame', frame(200))
    const before = ready().recording

    latest().onerror?.()
    await vi.advanceTimersByTimeAsync(1_000)
    run = { ...run, instance: 'b' }
    await connect()
    latest().send('frame', frame(0.1))

    expect(ready().recording).not.toBe(before)
    expect(ready().runKey).toBe('b:1')
    expect(ready().recording.frames.map((f) => f.t)).toEqual([0.1])
  })

  it('starts a new recording on a reset', async () => {
    await connect()
    latest().send('frame', frame(50))
    run = { ...run, run_id: 2, scenario: 'car-crash' }
    latest().send('reset', run)
    latest().send('frame', frame(0.1))
    await settle()
    expect(ready().scenario).toBe('car-crash')
    expect(ready().recording.frames.map((f) => f.t)).toEqual([0.1])
  })

  it('keeps retrying while the Twin is down, backing off, then recovers without a page reload', async () => {
    fetchMap.mockImplementation(async () => ({ ok: false, status: 502, json: async () => ({}) }))
    await connect() // the proxy answers the stream, the Twin does not answer the map
    expect(last()).toMatchObject({ status: 'connecting', problem: expect.stringContaining('502') })

    for (let i = 0; i < 5; i++) {
      latest().onerror?.()
      await vi.advanceTimersByTimeAsync(5_000)
    }
    expect(FakeSource.all.length).toBeGreaterThan(4)
    expect(FakeSource.all.slice(0, -1).every((s) => s.closed)).toBe(true) // only one stream open

    fetchMap.mockImplementation(async () => ({ ok: true, status: 200, json: async () => ({ dt: 0.1, map: {}, ...run }) }))
    await connect()
    expect(last().status).toBe('ready')
  })

  it('treats a stream that went silent as dead, but not one that pings', async () => {
    await connect()
    for (let i = 0; i < 4; i++) {
      await vi.advanceTimersByTimeAsync(5_000)
      latest().send('ping', {}) // paused Twin
    }
    expect(FakeSource.all).toHaveLength(1)
    expect(ready().connected).toBe(true)

    await vi.advanceTimersByTimeAsync(15_000) // 12 s of silence, the 1 s check, the 1 s retry
    expect(FakeSource.all[0].closed).toBe(true)
    expect(FakeSource.all.length).toBeGreaterThan(1)
  })

  it('survives an unparsable frame', async () => {
    const error = vi.spyOn(console, 'error').mockImplementation(() => {})
    await connect()
    latest().send('frame', '{"t": NaN}')
    latest().send('frame', frame(1))
    expect(ready().recording.frames.map((f) => f.t)).toEqual([1])
    expect(error).toHaveBeenCalledOnce()
    error.mockRestore()
  })

  it('does nothing after stop', async () => {
    await connect()
    const count = states.length
    stream.stop()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(states).toHaveLength(count)
    expect(FakeSource.all).toHaveLength(1)
  })
})
