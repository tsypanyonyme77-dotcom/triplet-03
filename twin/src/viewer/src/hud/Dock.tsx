import { ChevronsRight, Pause, Play, RotateCcw } from 'lucide-react'
import { useState } from 'react'
import type { PlaybackClock } from '../playback/clock'
import { speedText } from './format'
import { useLive } from './LiveContext'
import { Scrubber } from './Scrubber'

const LIVE_SPEEDS = [0.5, 1, 2, 4, 8]
const RECORDING_SPEEDS = [0.25, 0.5, 1, 2, 4]

/**
 * Bottom centre: the time controls, one set. In a live run play, pause, speed and restart steer the
 * Twin's own clock (the server runs the city); the slider only looks back through what was streamed.
 * Playing a recording they steer the playback clock instead.
 */
export function Dock({ clock }: { clock: PlaybackClock }) {
  const live = useLive()
  const [paused, setPaused] = useState(clock.paused)
  const [rate, setRate] = useState(clock.rate)

  const isPaused = live?.status ? live.status.paused : paused
  const speed = live?.status ? live.status.speed : rate
  const togglePlay = () => {
    if (live) void live.run({ action: isPaused ? 'resume' : 'pause' })
    else {
      clock.paused = !clock.paused
      setPaused(clock.paused)
    }
  }
  const pickSpeed = (r: number) => {
    if (live) void live.run({ action: 'speed', speed: r })
    else {
      clock.rate = r
      setRate(r)
    }
  }

  return (
    <div className="hud-card dock">
      {live && (
        <button type="button" className="round ghost" title="Start this scenario again from the beginning" onClick={() => void live.run({ action: 'reset' })}>
          <RotateCcw size={18} />
        </button>
      )}
      <button type="button" className="round play" title={isPaused ? 'Play' : 'Pause'} onClick={togglePlay}>
        {isPaused ? <Play size={22} fill="currentColor" /> : <Pause size={22} fill="currentColor" />}
      </button>
      <div className="speed-chips" role="group" aria-label="Speed">
        <ChevronsRight size={16} aria-hidden />
        {(live ? LIVE_SPEEDS : RECORDING_SPEEDS).map((r) => (
          <button key={r} type="button" className={`speed${r === speed ? ' on' : ''}`} onClick={() => pickSpeed(r)}>
            {speedText(r)}
          </button>
        ))}
      </div>
      <Scrubber clock={clock} />
    </div>
  )
}
