import type { EntityTuple, Frame } from './types'

/** Every id that appears at least once in the recording, in first-seen order. */
export function collectIds(frames: Frame[], pick: (f: Frame) => EntityTuple[]): string[] {
  const seen = new Set<string>()
  for (const frame of frames) {
    for (const entity of pick(frame)) seen.add(entity[0])
  }
  return [...seen]
}
