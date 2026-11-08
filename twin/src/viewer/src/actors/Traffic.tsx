import { usePlayback } from '../playback/ClockContext'
import type { Frame } from '../recording/types'
import { useEntityIds } from '../recording/useEntityIds'
import { CarActor } from './CarActor'
import { CAR_MODELS, unitModel } from './modelCatalog'
import { PedestrianActor } from './PedestrianActor'
import { personLook } from './personLook'

const pickCars = (f: Frame) => f.cars
const pickPeds = (f: Frame) => f.pedestrians

/** Every car, emergency vehicle and pedestrian in the recording, each with its 3D model; people each look their own way. */
export function Traffic() {
  const { recording } = usePlayback()
  const carIds = useEntityIds(recording, pickCars)
  const pedIds = useEntityIds(recording, pickPeds)

  return (
    <>
      {carIds.map((id, i) => (
        <CarActor key={id} id={id} model={unitModel(id) ?? CAR_MODELS[i % CAR_MODELS.length]} />
      ))}
      {pedIds.map((id) => (
        <PedestrianActor key={id} id={id} look={personLook(id)} />
      ))}
    </>
  )
}
