import type { CityMap } from '../recording/types'
import { headingToYaw } from './coords'
import { TrafficLight } from './TrafficLight'

const POLE_BEYOND_KERB_M = 0.6

/**
 * A signal head for every signalised approach, on the right-hand sidewalk level
 * with the stop line, facing the drivers who must obey it.
 */
export function TrafficLights({ map }: { map: CityMap }) {
  const lit = new Set(map.roads.nodes.filter((n) => n.has_light).map((n) => n.id))
  const kerb = map.profile.kerb_m
  const laneMid = map.profile.driving_outer_m / 2
  const heads = map.stop_lines
    .filter((s) => lit.has(s.approach[1]))
    .map((s) => {
      const ux = Math.cos(s.heading)
      const uy = Math.sin(s.heading)
      const out = kerb + POLE_BEYOND_KERB_M - laneMid // stop line centre sits mid-lanes; move to the sidewalk
      const x = s.x + uy * out // right-hand perpendicular of travel is (uy, -ux)
      const y = s.y - ux * out
      return {
        key: `${s.approach[0]}-${s.approach[1]}`,
        nodeId: s.approach[1],
        fromNodeId: s.approach[0],
        position: [x, 0, -y] as [number, number, number],
        yaw: headingToYaw(s.heading + Math.PI, '+z'), // lamp faces oncoming drivers
      }
    })

  return (
    <>
      {heads.map((h) => (
        <TrafficLight key={h.key} nodeId={h.nodeId} fromNodeId={h.fromNodeId} position={h.position} yaw={h.yaw} />
      ))}
    </>
  )
}
