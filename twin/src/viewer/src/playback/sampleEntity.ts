import type { EntityTuple, Frame } from '../recording/types'
import { angleDelta } from '../scene/coords'
import { frameIndex } from './frameAt'

export interface EntitySample {
  x: number
  y: number
  heading: number
  speed: number
  status: string
  /** front-wheel angle (rad, + = left) and acceleration (m/s^2); 0 when not recorded */
  steer: number
  accel: number
}

function find(list: EntityTuple[], id: string): EntityTuple | undefined {
  for (const entity of list) if (entity[0] === id) return entity
  return undefined
}

/**
 * Entity state at playback time `time`, linearly interpolated between the two
 * surrounding 10 Hz frames so motion looks smooth at the display frame rate.
 * Returns undefined when the entity does not exist at that time.
 */
export function sampleEntity(
  frames: Frame[],
  dt: number,
  time: number,
  id: string,
  pick: (f: Frame) => EntityTuple[],
): EntitySample | undefined {
  if (frames.length === 0) return undefined
  const exact = frameIndex(frames, dt, time) // frames[0] is t = dt in a recording
  const i = Math.min(Math.max(Math.floor(exact), 0), frames.length - 1)
  const j = Math.min(i + 1, frames.length - 1)
  const a = find(pick(frames[i]), id)
  if (!a) return undefined
  const b = find(pick(frames[j]), id) ?? a
  const k = Math.min(Math.max(exact - i, 0), 1)

  // a jump (parking pull-in end, respawn) bigger than any real 0.1 s move: don't smear it
  const teleport = Math.hypot(b[1] - a[1], b[2] - a[2]) > 5
  const s = teleport ? 0 : k
  return {
    x: a[1] + (b[1] - a[1]) * s,
    y: a[2] + (b[2] - a[2]) * s,
    heading: a[3] + angleDelta(a[3], b[3]) * s,
    speed: a[4] + (b[4] - a[4]) * s,
    status: s < 0.5 ? a[5] : b[5],
    steer: (a[6] ?? 0) + ((b[6] ?? 0) - (a[6] ?? 0)) * s,
    accel: (a[7] ?? 0) + ((b[7] ?? 0) - (a[7] ?? 0)) * s,
  }
}
