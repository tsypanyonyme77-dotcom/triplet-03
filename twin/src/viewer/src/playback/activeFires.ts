import type { Frame } from '../recording/types'

export interface BurningBuilding {
  buildingId: string
  /** 0 when it starts, 1 at full strength */
  strength: number
}

/** The buildings burning in a frame. Recordings made before fires have none. */
export function activeFires(frame: Frame): BurningBuilding[] {
  return (frame.fires ?? []).map(([buildingId, strength]) => ({ buildingId, strength }))
}
