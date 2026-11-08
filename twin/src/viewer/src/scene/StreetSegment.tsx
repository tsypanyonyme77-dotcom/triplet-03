import type { Street } from './cityLayout'

const ASPHALT = '#3b3d40'
const MARKING = '#f2f0e6'
const DASH_M = 3
const GAP_M = 4

/** Asphalt strip for one street, extended over both intersections, with a dashed centreline. */
export function StreetSegment({ street, halfWidth }: { street: Street; halfWidth: number }) {
  const { a, b } = street
  const dx = b.x - a.x
  const dy = b.y - a.y
  const length = Math.hypot(dx, dy)
  const yaw = Math.atan2(dy, dx) // rotation about +Y; sim y maps to -Z, see coords.ts
  const mx = (a.x + b.x) / 2
  const my = (a.y + b.y) / 2

  const markedLength = length - halfWidth * 2
  const dashes = Math.max(0, Math.floor(markedLength / (DASH_M + GAP_M)))
  const start = -((dashes - 1) * (DASH_M + GAP_M)) / 2

  return (
    <group position={[mx, 0, -my]} rotation-y={yaw}>
      <mesh rotation-x={-Math.PI / 2} position-y={0.01} receiveShadow>
        <planeGeometry args={[length + halfWidth * 2, halfWidth * 2]} />
        <meshStandardMaterial color={ASPHALT} />
      </mesh>
      {Array.from({ length: dashes }, (_, i) => (
        <mesh key={i} rotation-x={-Math.PI / 2} position={[start + i * (DASH_M + GAP_M), 0.02, 0]}>
          <planeGeometry args={[DASH_M, 0.2]} />
          <meshStandardMaterial color={MARKING} />
        </mesh>
      ))}
    </group>
  )
}
