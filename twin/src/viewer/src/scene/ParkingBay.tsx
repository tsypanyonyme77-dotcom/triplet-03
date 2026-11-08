import { useMemo } from 'react'
import { bayLines } from './bayMarkings'

const PAINT = '#f4f2ea'

/**
 * White markings of one parking bay. `heading` is the sim heading of the lane: rotating
 * by it about +Y turns local +x into the direction of travel and local +z toward the kerb.
 */
export function ParkingBay({
  x,
  y,
  heading,
  length,
  width,
}: {
  x: number
  y: number
  heading: number
  length: number
  width: number
}) {
  const lines = useMemo(() => bayLines(length, width), [length, width])
  return (
    <group position={[x, 0.025, -y]} rotation-y={heading}>
      {lines.map((l, i) => (
        <mesh key={i} position={[l.x, 0, l.z]} receiveShadow>
          <boxGeometry args={[l.along, 0.01, l.across]} />
          <meshStandardMaterial color={PAINT} />
        </mesh>
      ))}
    </group>
  )
}
