import { useEffect, useState } from 'react'
import type { PlaybackClock } from '../playback/clock'

/** The clock's time, for display: read a few times a second (the scene reads it at 60 fps by itself). */
export function useClockTime(clock: PlaybackClock, everyMs = 250): number {
  const [time, setTime] = useState(clock.time)
  useEffect(() => {
    const id = window.setInterval(() => setTime(clock.time), everyMs)
    return () => window.clearInterval(id)
  }, [clock, everyMs])
  return time
}
