import type { CrosswalkData } from '../recording/types'

const PAINT = '#f4f2ea'
const STRIPE_M = 0.6
const GAP_M = 0.6

/**
 * Zebra stripes across the asphalt only: the crosswalk's ends sit on the sidewalk
 * centrelines, so half a sidewalk is trimmed off each end.
 */
export function Crosswalk({ data, sidewalkWidth }: { data: CrosswalkData; sidewalkWidth: number }) {
  const [ax, ay] = data.a
  const [bx, by] = data.b
  const total = Math.hypot(bx - ax, by - ay)
  const painted = total - sidewalkWidth
  const stripes = Math.max(1, Math.floor((painted + GAP_M) / (STRIPE_M + GAP_M)))
  const start = -((stripes - 1) * (STRIPE_M + GAP_M)) / 2
  const yaw = Math.atan2(by - ay, bx - ax) // local +X runs a -> b (sim y maps to -Z)

  return (
    <group position={[(ax + bx) / 2, 0.025, -(ay + by) / 2]} rotation-y={yaw}>
      {Array.from({ length: stripes }, (_, i) => (
        <mesh key={i} rotation-x={-Math.PI / 2} position-x={start + i * (STRIPE_M + GAP_M)} receiveShadow>
          <planeGeometry args={[STRIPE_M, data.width]} />
          <meshStandardMaterial color={PAINT} />
        </mesh>
      ))}
    </group>
  )
}
