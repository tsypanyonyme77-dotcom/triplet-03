import { Edges } from '@react-three/drei'
import type { ThreeEvent } from '@react-three/fiber'
import type { FloodZoneData } from '../recording/types'
import { gratePosition } from './drainView'

const PICK_HEIGHT_M = 0.05

/** One street's storm drain: a grate by the kerb at the low point, and the dip around it to click on. */
export function Drain({ zone, selected, onSelect }: { zone: FloodZoneData; selected: boolean; onSelect: (id: string) => void }) {
  const [gx, gy] = gratePosition(zone)
  const select = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation()
    onSelect(zone.id)
  }
  return (
    <>
      <mesh position={[gx, 0.03, -gy]} rotation-y={zone.heading} onClick={select}>
        <boxGeometry args={[1.2, 0.04, 0.6]} />
        <meshStandardMaterial color="#2b2f33" metalness={0.6} roughness={0.5} />
        {selected && <Edges color="#ffd400" lineWidth={3} />}
      </mesh>
      {/* the whole dip is the target, so a street is easy to pick from far away */}
      <group position={[zone.x, PICK_HEIGHT_M, -zone.y]} rotation-y={zone.heading}>
        <mesh rotation-x={-Math.PI / 2} onClick={select}>
          <planeGeometry args={[2 * zone.half_length_m, 2 * zone.road_half_width_m]} />
          <meshBasicMaterial color="#ffd400" transparent opacity={selected ? 0.18 : 0} depthWrite={false} />
        </mesh>
      </group>
    </>
  )
}
