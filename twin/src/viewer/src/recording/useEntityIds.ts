import { useEffect, useState } from 'react'
import { collectIds } from './entityIds'
import type { EntityTuple, Frame, Recording } from './types'

const CHECK_MS = 500

/**
 * Every id that has appeared in the recording, in first-seen order. A recording is complete
 * when it loads; a live one grows (frames are appended in place), so new frames are scanned
 * twice a second and new ids (crew getting out, a casualty) get their actor.
 */
export function useEntityIds(recording: Recording, pick: (f: Frame) => EntityTuple[]): string[] {
  const [ids, setIds] = useState<string[]>(() => collectIds(recording.frames, pick))

  useEffect(() => {
    let scanned = recording.frames.length
    const known = new Set(collectIds(recording.frames, pick))
    setIds([...known])
    const id = window.setInterval(() => {
      const frames = recording.frames
      if (frames.length === scanned) return
      let added = false
      for (const entity of collectIds(frames.slice(scanned), pick)) {
        if (!known.has(entity)) {
          known.add(entity)
          added = true
        }
      }
      scanned = frames.length
      if (added) setIds([...known])
    }, CHECK_MS)
    return () => window.clearInterval(id)
    // `pick` is a stable selector per call site
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recording])

  return ids
}
