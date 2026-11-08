import { useEffect, useMemo, useRef, useState } from 'react'
import type { PlaybackClock } from '../playback/clock'
import { frameAt } from '../playback/frameAt'
import type { Recording } from '../recording/types'
import { hudSnapshot, type HudSnapshot } from './derive'
import { diffSnapshots, type HudEvent } from './events'

const LOOK_MS = 250
const JUMP_S = 2 // a bigger step in playback time is a seek, not something happening

/**
 * The overlay's view of the city, looked at four times a second (the 3D scene reads the clock at 60 fps
 * itself; the overlay does not need to). `onEvents` gets what changed between two looks, unless the clock
 * jumped (a seek, a restart): moving the slider is not news.
 */
export function useHud(clock: PlaybackClock, recording: Recording, onEvents: (events: HudEvent[]) => void): HudSnapshot | null {
  const buildings = useMemo(() => new Map((recording.map.buildings ?? []).map((b) => [b.id, b])), [recording.map])
  const [snapshot, setSnapshot] = useState<HudSnapshot | null>(null)
  const last = useRef<{ snap: HudSnapshot; key: string; time: number } | null>(null)
  const emit = useRef(onEvents)
  emit.current = onEvents

  useEffect(() => {
    last.current = null
    const look = () => {
      if (recording.frames.length === 0) return
      const time = clock.time
      const snap = hudSnapshot(frameAt(recording.frames, recording.dt, time), buildings)
      const key = JSON.stringify(snap)
      const before = last.current
      if (before && before.key === key) {
        before.time = time
        return
      }
      const steady = before !== null && time >= before.time && time - before.time <= JUMP_S
      const events = steady ? diffSnapshots(before.snap, snap, `${Math.round(time * 10)}`) : []
      last.current = { snap, key, time }
      setSnapshot(snap)
      if (events.length > 0) emit.current(events)
    }
    look()
    const id = window.setInterval(look, LOOK_MS)
    return () => window.clearInterval(id)
  }, [clock, recording, buildings])

  return snapshot
}
