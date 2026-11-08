import type { CityMap } from '../recording/types'

/** One way to look through a traffic camera: from its pole at the junction, down one of its streets. */
export interface CctvView {
  id: string
  cameraId: string
  label: string
  /** world coordinates (x, up, -sim y) */
  eye: [number, number, number]
  look: [number, number, number]
}

const POLE_HEIGHT_M = 7
const BEHIND_M = 4 // the pole stands this far back from the junction centre ...
const ASIDE_M = 7 // ... and this far to the right of the street, at the corner
const LOOK_AHEAD_M = 30

/** Every camera, once per street it looks down. */
export function cctvViews(map: CityMap): CctvView[] {
  const nodes = new Map(map.roads.nodes.map((n) => [n.id, n]))
  return (map.cameras ?? []).flatMap((cam) =>
    cam.looks_toward.flatMap((to) => {
      const n = nodes.get(to)
      if (!n) return []
      const len = Math.hypot(n.x - cam.x, n.y - cam.y) || 1
      const [dx, dy] = [(n.x - cam.x) / len, (n.y - cam.y) / len]
      const [rx, ry] = [dy, -dx] // right of the street, looking down it
      const ex = cam.x - dx * BEHIND_M + rx * ASIDE_M
      const ey = cam.y - dy * BEHIND_M + ry * ASIDE_M
      const lx = cam.x + dx * LOOK_AHEAD_M
      const ly = cam.y + dy * LOOK_AHEAD_M
      return [
        {
          id: `${cam.id}>${to}`,
          cameraId: cam.id,
          label: `${cam.id}, looking down street ${cam.node}-${to}`,
          eye: [ex, POLE_HEIGHT_M, -ey] as [number, number, number],
          look: [lx, 0, -ly] as [number, number, number],
        },
      ]
    }),
  )
}
