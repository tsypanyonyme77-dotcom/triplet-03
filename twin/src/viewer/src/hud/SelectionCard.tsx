import { Building2, Flame, X } from 'lucide-react'
import { useState } from 'react'
import { igniteFire } from '../api/twinApi'
import type { BuildingData } from '../recording/types'

/** The building you clicked, with the fire simulator's button (live runs only). */
export function SelectionCard({ building, canIgnite, onClose }: { building: BuildingData; canIgnite: boolean; onClose: () => void }) {
  const [message, setMessage] = useState<string | null>(null)
  const start = () =>
    igniteFire(building.id)
      .then((r) => setMessage(r.status === 'ignited' ? 'It is on fire!' : 'Already burning.'))
      .catch((e: unknown) => setMessage(String(e)))
  return (
    <div className="hud-card selection-card">
      <span className="selection-icon">
        <Building2 size={20} />
      </span>
      <span className="selection-text">
        <strong>{building.id}</strong>
        <span>
          {building.width.toFixed(0)} by {building.depth.toFixed(0)} m, {building.height.toFixed(0)} m tall
        </span>
        {message && <em>{message}</em>}
      </span>
      {canIgnite && (
        <button type="button" className="big-button fire" onClick={() => void start()}>
          <Flame size={16} /> Start a fire
        </button>
      )}
      <button type="button" className="round ghost small" aria-label="Close" onClick={onClose}>
        <X size={16} />
      </button>
    </div>
  )
}
