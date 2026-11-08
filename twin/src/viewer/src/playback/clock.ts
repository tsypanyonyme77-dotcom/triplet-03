/**
 * Playback time shared by the render loop and the UI. Mutable on purpose:
 * actors read it inside useFrame at 60 fps, where React state would be too slow.
 *
 * Time is simulation time (the frames' `t`). A recording plays from 0 to its end and loops.
 * A live stream (`live`) grows while it plays: the clock follows its newest frame, LIVE_LAG_S
 * behind so there is always a next frame to interpolate toward; seeking back stops following,
 * seeking to the end (or play past it) follows again.
 */
export const LIVE_LAG_S = 0.3

export class PlaybackClock {
  time = 0
  rate = 1
  paused = false
  followLive = true
  readonly live: boolean
  private readonly range: () => [number, number]

  constructor(duration: number | (() => [number, number]), live = false) {
    this.range = typeof duration === 'number' ? () => [0, duration] : duration
    this.live = live
  }

  get start(): number {
    return this.range()[0]
  }

  get duration(): number {
    return this.range()[1]
  }

  advance(deltaSeconds: number): void {
    if (this.paused) return
    const [start, end] = this.range()
    if (this.live) {
      if (this.followLive) {
        this.time = Math.max(start, end - LIVE_LAG_S)
        return
      }
      this.time = Math.max(start, this.time + deltaSeconds * this.rate)
      if (this.time >= end - LIVE_LAG_S) this.followLive = true
      return
    }
    this.time = (this.time + deltaSeconds * this.rate) % end
  }

  seek(time: number): void {
    const [start, end] = this.range()
    this.time = Math.min(Math.max(time, start), end)
    if (this.live) this.followLive = this.time >= end - 0.5
  }
}
