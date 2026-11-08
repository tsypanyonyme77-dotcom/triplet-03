import type { PedestrianModel } from './modelCatalog'

export type Gait = 'idle' | 'walk' | 'run'

// Separate thresholds up and down (hysteresis): a speed hovering around one value,
// e.g. while waiting at a kerb or being nudged apart, must not flip the clip every frame.
const START_WALKING_MS = 0.25
const STOP_WALKING_MS = 0.1
const START_RUNNING_MS = 2.4 // between a brisk walk (~1.8) and a jog (~2.5)
const STOP_RUNNING_MS = 2.0

export function nextGait(current: Gait | undefined, speed: number): Gait {
  switch (current) {
    case 'run':
      return speed < STOP_WALKING_MS ? 'idle' : speed < STOP_RUNNING_MS ? 'walk' : 'run'
    case 'walk':
      return speed < STOP_WALKING_MS ? 'idle' : speed > START_RUNNING_MS ? 'run' : 'walk'
    case 'idle':
      return speed > START_RUNNING_MS ? 'run' : speed > START_WALKING_MS ? 'walk' : 'idle'
    default:
      return speed > START_RUNNING_MS ? 'run' : speed > START_WALKING_MS ? 'walk' : 'idle'
  }
}

// Slowest the clips play. Crowds and queues shuffle along at 0.2 to 0.5 m/s; with a higher floor
// (it was 0.5, i.e. 0.7 m/s for a walk) the legs outrun the ground and the figure glides.
const MIN_CLIP_RATE = 0.2
const MAX_CLIP_RATE = 1.6

/** Clip playback rate that makes feet match ground speed (no foot sliding). */
export function clipTimeScale(gait: Gait, speed: number, model: PedestrianModel): number {
  if (gait === 'idle') return 1
  const native = model.clipSpeed[gait]
  return Math.min(Math.max(speed / native, MIN_CLIP_RATE), MAX_CLIP_RATE)
}
