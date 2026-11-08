import type { ModelFacing } from '../scene/coords'

// Per-model facts measured from the .glb files with sim/inspect_glb.py.

export interface CarModel {
  url: string
  facing: ModelFacing
  wheelRadius: number // in model units, for wheel spin
  /** bounding box in model units: length along the model's long axis, width across it, and
   * where along the long axis its centre is (files are not always centred) */
  size: { length: number; width: number; centerZ: number }
}

// Kenney Car Kit 3.1, CC0. Sizes from tools/inspect_glb.py; the viewer scales each model
// to fit inside the sim's vehicle body (actors/carFit.ts).
const kenney = (name: string, length: number, width: number, centerZ: number): CarModel => ({
  url: `/models/cars/${name}.glb`,
  facing: '+z',
  wheelRadius: 0.3,
  size: { length, width, centerZ },
})

// civilian cars only: the police car, ambulance and fire truck are kept for the emergency units
export const CAR_MODELS: CarModel[] = [
  kenney('sedan', 2.55, 1.5, -0.025),
  kenney('taxi', 2.75, 1.5, -0.025),
  kenney('suv', 2.7, 1.5, 0),
  kenney('van', 2.75, 1.5, -0.025),
  kenney('hatchback-sports', 2.85, 1.3, -0.025),
]
export const AMBULANCE_MODEL: CarModel = kenney('ambulance', 3.25, 1.5, -0.025)
export const POLICE_MODEL: CarModel = kenney('police', 3.1, 1.5, 0)
export const FIRETRUCK_MODEL: CarModel = kenney('firetruck', 3.4, 1.5, 0)

/** Emergency units are recorded with ids amb1, police1, fire1 (two_blocks/record.py). */
export function unitModel(id: string): CarModel | null {
  if (id.startsWith('amb')) return AMBULANCE_MODEL
  if (id.startsWith('police')) return POLICE_MODEL
  if (id.startsWith('fire')) return FIRETRUCK_MODEL
  return null
}

/** The sim's vehicle body, for recordings made before they carried it (map.vehicle). */
export const LEGACY_VEHICLE_BODY = { length: 4.5, width: 2.0 }

export interface PedestrianModel {
  label: string
  url: string
  scale: number
  facing: ModelFacing
  clips: { idle: string; walk: string; run: string }
  /** ground speed (m/s, after scaling) the walk/run clips show at timeScale 1; tuned by eye */
  clipSpeed: { walk: number; run: number }
  /** the material that is clothing, recoloured per person */
  outfitMaterial: string
}

export const PEDESTRIAN_MODELS = {
  soldier: {
    label: 'Soldier (three.js example, Mixamo animation)',
    url: '/models/people/Soldier.glb',
    scale: 0.95, // 1.83 m tall in the file
    facing: '-z',
    clips: { idle: 'Idle', walk: 'Walk', run: 'Run' },
    clipSpeed: { walk: 1.4, run: 3.6 },
    outfitMaterial: 'VanguardBodyMat',
  },
  robot: {
    label: 'RobotExpressive (Quaternius, CC0)',
    url: '/models/people/RobotExpressive.glb',
    scale: 0.42, // ~4.1 units tall in the file -> ~1.7 m
    facing: '+z',
    clips: { idle: 'Idle', walk: 'Walking', run: 'Running' },
    clipSpeed: { walk: 1.2, run: 3.0 },
    outfitMaterial: 'Main',
  },
} satisfies Record<string, PedestrianModel>

export type PedestrianModelKey = keyof typeof PEDESTRIAN_MODELS
