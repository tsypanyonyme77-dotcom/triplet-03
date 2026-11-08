import type { BuildingData } from '../recording/types'
import { Building } from './Building'

/** The buildings the engine knows, each drawn in its own look; the selected one is outlined. */
export function Buildings({
  buildings,
  selectedId,
  onSelect,
}: {
  buildings: BuildingData[]
  selectedId: string | null
  onSelect: (id: string) => void
}) {
  return (
    <group>
      {buildings.map((b) => (
        <Building
          key={b.id}
          spec={b}
          selected={b.id === selectedId}
          onSelect={onSelect}
        />
      ))}
    </group>
  )
}
