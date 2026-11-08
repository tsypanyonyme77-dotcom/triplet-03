import type { CityMap } from '../recording/types'
import { headingToYaw } from './coords'
import { PedestrianSignal } from './PedestrianSignal'

const BESIDE_CROSSWALK_M = 0.4

/** A signal at both ends of every signalised crosswalk, beside it, facing the people across the road. */
export function PedestrianSignals({ map }: { map: CityMap }) {
  const heads = map.crosswalks.flatMap((cw) => {
    if (!cw.signalised || cw.node === undefined) return []
    const nodeId = cw.node
    const heading = Math.atan2(cw.b[1] - cw.a[1], cw.b[0] - cw.a[0])
    const out = cw.width / 2 + BESIDE_CROSSWALK_M
    const sideX = -Math.sin(heading) * out
    const sideY = Math.cos(heading) * out
    return [
      { key: `${cw.id}-a`, nodeId, x: cw.a[0] + sideX, y: cw.a[1] + sideY, yaw: headingToYaw(heading, '+z') },
      { key: `${cw.id}-b`, nodeId, x: cw.b[0] + sideX, y: cw.b[1] + sideY, yaw: headingToYaw(heading + Math.PI, '+z') },
    ]
  })

  return (
    <>
      {heads.map((h) => (
        <PedestrianSignal key={h.key} nodeId={h.nodeId} position={[h.x, 0, -h.y]} yaw={h.yaw} />
      ))}
    </>
  )
}
