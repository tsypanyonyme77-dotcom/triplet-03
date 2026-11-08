import type { Frame } from '../recording/types'

/**
 * Fractional index of sim time `time` in `frames`. Frames are normally dt apart from frames[0].t
 * (a recording starts at t = dt; a live stream joined mid-run starts later), but a live stream
 * can have gaps (a dropped connection), so that estimate is checked and, when wrong, the time
 * is searched for. Not rounded or clamped.
 */
export function frameIndex(frames: Frame[], dt: number, time: number): number {
  const origin = frames.length > 0 ? frames[0].t : dt
  const estimate = (time - origin) / dt
  const last = frames.length - 1
  if (last < 0 || estimate <= 0) return estimate
  const floor = Math.floor(estimate)
  if (floor < last && frames[floor].t <= time && time < frames[floor + 1].t) return estimate
  if (time >= frames[last].t) return last + (time - frames[last].t) / dt

  let low = 0 // frames[low].t <= time < frames[high].t
  let high = last
  while (high - low > 1) {
    const middle = (low + high) >> 1
    if (frames[middle].t <= time) low = middle
    else high = middle
  }
  return low + (time - frames[low].t) / (frames[high].t - frames[low].t)
}

/** The recorded frame at or just before `time` (no interpolation). */
export function frameAt(frames: Frame[], dt: number, time: number): Frame {
  const i = Math.min(Math.max(Math.round(frameIndex(frames, dt, time)), 0), frames.length - 1)
  return frames[i]
}
