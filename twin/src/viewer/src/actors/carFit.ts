import type { VehicleBody } from '../recording/types'
import type { CarModel } from './modelCatalog'

/** How a car model is drawn on its sim body. */
export interface CarFit {
  scale: number
  /** shift along the body's long axis that puts the model's centre on the body's centre */
  offsetZ: number
  /** drawn size (m) */
  length: number
  width: number
}

/**
 * The largest uniform scale at which the model fits inside the sim body, centred on it.
 * Drawn cars are then never bigger than what the sim checks for overlap: two cars that
 * look like they touch really do.
 */
export function fitCar(model: CarModel, body: VehicleBody): CarFit {
  const { length, width, centerZ } = model.size
  const scale = Math.min(body.length / length, body.width / width)
  return { scale, offsetZ: -centerZ * scale, length: length * scale, width: width * scale }
}
