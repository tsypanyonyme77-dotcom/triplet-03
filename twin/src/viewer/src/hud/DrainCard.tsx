import { CloudRain, Waves, X } from 'lucide-react'
import { useState } from 'react'
import { floodStreet } from '../api/twinApi'
import type { PlaybackClock } from '../playback/clock'
import { frameAt } from '../playback/frameAt'
import type { FloodZoneData, Recording } from '../recording/types'
import { drainState, streetName } from '../scene/drainView'
import { useClockTime } from './useClockTime'

/** The street drain you clicked: how much water there is, and the flood simulator's button (live runs only). */
export function DrainCard({
  zone,
  clock,
  recording,
  canFlood,
  onClose,
}: {
  zone: FloodZoneData
  clock: PlaybackClock
  recording: Recording
  canFlood: boolean
  onClose: () => void
}) {
  const [message, setMessage] = useState<string | null>(null)
  const time = useClockTime(clock)
  const now = drainState(frameAt(recording.frames, recording.dt, time), zone.id)
  const start = () =>
    floodStreet(zone.id)
      .then((r) => setMessage(r.status === 'started' ? 'Drain blocked, downpour coming!' : 'It is already pouring there.'))
      .catch((e: unknown) => setMessage(String(e)))
  const facts = [
    now.depth > 0.005 ? `water ${now.depth.toFixed(2)} m` : 'dry',
    now.rain ? `rain ${Math.round(now.rain)} mm/h` : null,
    now.blocked ? 'drain blocked' : 'drain clear',
    now.pumpOn ? 'pump on' : null,
  ].filter(Boolean)

  return (
    <div className="hud-card selection-card">
      <span className="selection-icon">
        <Waves size={20} />
      </span>
      <span className="selection-text">
        <strong>Drain of {streetName(zone)}</strong>
        <span>{facts.join(' · ')}</span>
        {message && <em>{message}</em>}
      </span>
      {canFlood && (
        <button type="button" className="big-button water" onClick={() => void start()} title="Block the drain and bring a downpour over this street">
          <CloudRain size={16} /> Block and flood
        </button>
      )}
      <button type="button" className="round ghost small" aria-label="Close" onClick={onClose}>
        <X size={16} />
      </button>
    </div>
  )
}
