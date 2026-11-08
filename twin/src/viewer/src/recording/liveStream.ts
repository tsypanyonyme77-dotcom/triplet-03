import { TWIN } from '../api/twinApi'
import type { Frame, Recording } from './types'

/** Frames kept per run: 20 minutes at 10 Hz. A longer run drops its oldest frames. */
const MAX_FRAMES = 12_000
/** The Twin pings a quiet stream every 5 s: this long without any message means it is dead. */
const STALL_MS = 12_000
const RETRY_MIN_MS = 1_000
const RETRY_MAX_MS = 5_000

export type LiveState =
  | { status: 'connecting'; problem: string | null }
  /** `runKey` changes when the Twin starts a new run or restarts; `connected` is false while
   * the stream is down: the scene stays, frozen on its last frame, until it is back. */
  | { status: 'ready'; recording: Recording; runKey: string; scenario: string; connected: boolean }

interface Hello {
  instance: string
  run_id: number
}
interface MapBody extends Hello {
  dt: number
  map: Recording['map']
  scenario: string
}

const keyOf = (run: Hello) => `${run.instance}:${run.run_id}`

/**
 * A recording that grows: the Twin's map (GET /twin/live/map) and its frames as they stream
 * (GET /twin/stream/frames, server-sent events). Frames are appended to recording.frames in
 * place, so playback reads them without re-rendering; a new run (a `reset` event, or a `hello`
 * from another run or a restarted Twin) replaces the recording and the scene is rebuilt.
 *
 * It never gives up. A browser's EventSource retries by itself only after some failures: an
 * HTTP error from the proxy (the Twin down) closes it for good. So every failure is handled
 * here, the same way: close the stream, try again in a moment, and ask the `hello` whether
 * this is still the run on screen. If it is, frames carry on after a gap.
 */
export class LiveStream {
  private source: EventSource | null = null
  private recording: Recording | null = null
  private state: LiveState = { status: 'connecting', problem: null }
  private run: { key: string; scenario: string } | null = null
  private pending: Frame[] = []
  private loadId = 0
  private stopped = false
  private retryMs = RETRY_MIN_MS
  private retryTimer: ReturnType<typeof setTimeout> | undefined
  private stallTimer: ReturnType<typeof setInterval> | undefined
  private lastMessage = 0
  private readonly onChange: (state: LiveState) => void

  constructor(onChange: (state: LiveState) => void) {
    this.onChange = onChange
  }

  start(): void {
    this.open()
    this.stallTimer = setInterval(() => {
      if (this.source && Date.now() - this.lastMessage > STALL_MS) this.fail('no data from the Twin')
    }, 1_000)
  }

  stop(): void {
    this.stopped = true
    this.closeSource()
    clearTimeout(this.retryTimer)
    clearInterval(this.stallTimer)
  }

  private publish(next: LiveState): void {
    this.state = next
    if (!this.stopped) this.onChange(next)
  }

  private open(): void {
    const source = new EventSource(`${TWIN}/stream/frames`)
    this.source = source
    this.lastMessage = Date.now()
    const on = (event: string, handle: (data: string) => void) =>
      source.addEventListener(event, (e) => {
        this.lastMessage = Date.now()
        try {
          handle((e as MessageEvent).data as string)
        } catch (err) {
          console.error(`live stream: bad ${event} event`, err)
        }
      })
    on('hello', (data) => this.onHello(JSON.parse(data) as Hello))
    on('frame', (data) => this.onFrame(JSON.parse(data) as Frame))
    on('reset', () => void this.load())
    on('ping', () => {})
    source.onerror = () => this.fail('the stream dropped')
  }

  private closeSource(): void {
    this.source?.close()
    this.source = null
  }

  private fail(problem: string): void {
    if (this.stopped || this.source === null) return
    this.closeSource()
    this.showDown(problem)
    clearTimeout(this.retryTimer)
    this.retryTimer = setTimeout(() => this.open(), this.retryMs)
    this.retryMs = Math.min(this.retryMs * 2, RETRY_MAX_MS)
  }

  private showDown(problem: string): void {
    if (this.state.status === 'ready') this.publish({ ...this.state, connected: false })
    else this.publish({ status: 'connecting', problem })
  }

  private onHello(hello: Hello): void {
    this.retryMs = RETRY_MIN_MS
    if (this.recording && this.run?.key === keyOf(hello)) {
      if (this.state.status === 'ready') this.publish({ ...this.state, connected: true })
      return
    }
    void this.load()
  }

  private onFrame(frame: Frame): void {
    const recording = this.recording
    if (recording === null) {
      this.pending.push(frame) // the map is on its way
      return
    }
    const frames = recording.frames
    if (frames.length > 0 && frame.t <= frames[frames.length - 1].t) return
    frames.push(frame)
    if (frames.length > MAX_FRAMES) frames.splice(0, frames.length - MAX_FRAMES)
  }

  /** A new run: its map, then the frames that came in while it loaded. */
  private async load(): Promise<void> {
    const id = ++this.loadId
    this.recording = null
    this.pending = []
    try {
      const res = await fetch(`${TWIN}/live/map`)
      if (!res.ok) throw new Error(`/live/map: HTTP ${res.status} (is the Twin running with TWIN_LIVE=1?)`)
      const body = (await res.json()) as MapBody
      if (id !== this.loadId || this.stopped) return
      const recording: Recording = { dt: body.dt, map: body.map, frames: [] }
      this.recording = recording
      this.run = { key: keyOf(body), scenario: body.scenario }
      for (const frame of this.pending) this.onFrame(frame)
      this.pending = []
      this.publish({
        status: 'ready',
        recording,
        runKey: this.run.key,
        scenario: body.scenario,
        connected: this.source !== null,
      })
    } catch (err) {
      if (id === this.loadId) this.fail(String(err))
    }
  }
}
