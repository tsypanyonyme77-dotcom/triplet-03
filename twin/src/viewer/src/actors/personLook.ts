import { PEDESTRIAN_MODELS, type PedestrianModel, type PedestrianModelKey } from './modelCatalog'

// clothing colours: muted everyday ones, a few bright
const OUTFITS = ['#3b5b92', '#8a3b3b', '#2f6b4f', '#6b5b95', '#c0843a', '#4a4a4a', '#9a9a9a', '#b5523b', '#2c7a8c', '#d1b25a', '#5d3a2b', '#e07a9a']
const MIN_HEIGHT = 0.9
const MAX_HEIGHT = 1.08
// how the crowd is split between the models, by weight
const MIX: [PedestrianModelKey, number][] = [
  ['soldier', 3],
  ['robot', 1],
]

export interface PersonLook {
  model: PedestrianModel
  /** clothing colour, for the model's outfit material */
  outfit: string
  /** times the model's own scale */
  height: number
}

function hash(text: string, salt: number): number {
  let h = 2166136261 ^ salt
  for (const ch of text) h = Math.imul(h ^ ch.charCodeAt(0), 16777619)
  return (h >>> 0) / 4294967296
}

/** How one person looks: depends only on their id, so they look the same on every load and in every viewer. */
export function personLook(id: string): PersonLook {
  const total = MIX.reduce((sum, [, w]) => sum + w, 0)
  let pick = hash(id, 1) * total
  let key = MIX[0][0]
  for (const [k, w] of MIX) {
    if (pick < w) {
      key = k
      break
    }
    pick -= w
  }
  return {
    model: PEDESTRIAN_MODELS[key],
    outfit: OUTFITS[Math.floor(hash(id, 2) * OUTFITS.length)],
    height: MIN_HEIGHT + hash(id, 3) * (MAX_HEIGHT - MIN_HEIGHT),
  }
}
