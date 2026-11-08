import { Radio } from 'lucide-react'
import type { PlaybackClock } from '../playback/clock'
import { clockText } from './format'
import { useClockTime } from './useClockTime'

/** A slider over the time there is: all of a recording, or what a live run has streamed so far. */
export function Scrubber({ clock }: { clock: PlaybackClock }) {
  const time = useClockTime(clock, 200)
  const behind = clock.live && !clock.followLive
  return (
    <div className="scrubber">
      <input
        type="range"
        aria-label="Time"
        min={clock.start}
        max={clock.duration}
        step={0.1}
        value={Math.min(time, clock.duration)}
        onChange={(e) => clock.seek(Number(e.target.value))}
      />
      <span className="scrubber-time">
        {clockText(time)}
        {!clock.live && ` / ${clockText(clock.duration)}`}
      </span>
      {behind && (
        <button type="button" className="pill-button" onClick={() => clock.seek(clock.duration)}>
          <Radio size={14} /> Back to live
        </button>
      )}
    </div>
  )
}
