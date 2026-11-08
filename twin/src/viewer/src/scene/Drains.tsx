import type { FloodZoneData } from '../recording/types'
import { Drain } from './Drain'

/** Every street's drain, selectable. */
export function Drains({ zones, selectedId, onSelect }: { zones: FloodZoneData[]; selectedId: string | null; onSelect: (id: string) => void }) {
  return (
    <>
      {zones.map((zone) => (
        <Drain key={zone.id} zone={zone} selected={zone.id === selectedId} onSelect={onSelect} />
      ))}
    </>
  )
}
