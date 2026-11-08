import type { Street } from './cityLayout'

const KERB = '#9a978f'
const KERB_W = 0.25
const KERB_H = 0.12

/**
 * Low kerb stones along both sides of a street. They stop `inset` metres short of
 * each end (the crossing streets' building line), leaving the corners flush so
 * crosswalks and intersections stay open, like dropped kerbs at a crossing.
 */
export function Kerbs({ street, kerbOffset, inset }: { street: Street; kerbOffset: number; inset: number }) {
  const { a, b } = street
  const length = Math.hypot(b.x - a.x, b.y - a.y)
  const run = length - inset * 2
  if (run <= 0) return null
  return (
    <group position={[(a.x + b.x) / 2, 0, -(a.y + b.y) / 2]} rotation-y={Math.atan2(b.y - a.y, b.x - a.x)}>
      {[-1, 1].map((side) => (
        <mesh key={side} position={[0, KERB_H / 2, side * kerbOffset]} castShadow receiveShadow>
          <boxGeometry args={[run, KERB_H, KERB_W]} />
          <meshStandardMaterial color={KERB} />
        </mesh>
      ))}
    </group>
  )
}
