import { Cctv, X } from 'lucide-react'
import type { PlaybackClock } from '../playback/clock'
import type { CctvView } from '../scene/cctv'
import { clockText } from './format'
import { useClockTime } from './useClockTime'

/** Looking through a CCTV camera: which one, a recording dot and the time, as on a security monitor. */
export function CctvBadge({ view, clock, onExit }: { view: CctvView; clock: PlaybackClock; onExit: () => void }) {
  const time = useClockTime(clock)
  return (
    <div className="hud-card cctv-badge" role="status">
      <span className="rec-dot" aria-hidden />
      <Cctv size={16} />
      <span>
        <strong>{view.label}</strong> · {clockText(time)}
      </span>
      <button type="button" className="round ghost small" aria-label="Leave the camera" onClick={onExit}>
        <X size={14} />
      </button>
    </div>
  )
}
