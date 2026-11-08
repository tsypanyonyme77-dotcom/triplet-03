import { Pause, Radio, Clapperboard, WifiOff } from 'lucide-react'
import type { PlaybackClock } from '../playback/clock'
import { clockText } from './format'
import { SCENARIO_NAMES } from './kindStyle'
import { useLive } from './LiveContext'
import { useClockTime } from './useClockTime'

/** Top left: is it live, which scenario, how far into it, and whether something is wrong with the connection. */
export function StatusPill({ clock, streamDown }: { clock: PlaybackClock; streamDown: boolean }) {
  const live = useLive()
  const time = useClockTime(clock)
  const paused = live?.status?.paused
  const scenario = live?.status ? (SCENARIO_NAMES[live.status.scenario] ?? live.status.scenario) : null
  const state = streamDown ? 'down' : paused ? 'paused' : live ? 'live' : 'rec'

  return (
    <div className={`hud-card status-pill ${state}`} role="status">
      <span className="status-badge">
        {state === 'down' ? <WifiOff size={14} /> : state === 'paused' ? <Pause size={14} /> : state === 'live' ? <Radio size={14} /> : <Clapperboard size={14} />}
        {state === 'down' ? 'Reconnecting' : state === 'paused' ? 'Paused' : state === 'live' ? 'Live' : 'Recording'}
      </span>
      {scenario && <span className="status-scenario">{scenario}</span>}
      <span className="status-clock" title="Simulated time">
        {clockText(live?.status?.sim_time_s ?? time)}
      </span>
    </div>
  )
}
