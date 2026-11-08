import type { BuildingData } from '../recording/types'

/** One sign on one wall, in three.js world coordinates (a plane faces +z before it is turned). */
export interface WallFace {
  side: 'east' | 'west' | 'north' | 'south'
  position: [number, number, number]
  rotationY: number
  width: number
  height: number
}

const GAP_M = 0.06            // the sign floats this far off the wall, enough not to flicker against it
const MAX_SIGN_WIDTH_M = 11
const SIGN_ASPECT = 4         // width / height of the painted sign
const FILL = 0.9              // of the wall's length

/**
 * The four signs of a building, one on each wall, so its name reads from any street.
 * Sim (x, y) is world (x, -y): the building's depth runs along world z.
 */
export function wallFaces(b: Pick<BuildingData, 'x' | 'y' | 'width' | 'depth' | 'height'>): WallFace[] {
  const cx = b.x
  const cz = -b.y
  const place = (length: number) => {
    const width = Math.min(length * FILL, MAX_SIGN_WIDTH_M, b.height * 0.6 * SIGN_ASPECT)
    return { width, height: width / SIGN_ASPECT }
  }
  const along = place(b.depth) // east and west walls run along z
  const across = place(b.width) // north and south walls run along x
  const y = (h: number) => Math.min(b.height * 0.6, b.height - h / 2 - 0.4)
  return [
    { side: 'east', position: [cx + b.width / 2 + GAP_M, y(along.height), cz], rotationY: Math.PI / 2, ...along },
    { side: 'west', position: [cx - b.width / 2 - GAP_M, y(along.height), cz], rotationY: -Math.PI / 2, ...along },
    { side: 'south', position: [cx, y(across.height), cz + b.depth / 2 + GAP_M], rotationY: 0, ...across },
    { side: 'north', position: [cx, y(across.height), cz - b.depth / 2 - GAP_M], rotationY: Math.PI, ...across },
  ]
}
