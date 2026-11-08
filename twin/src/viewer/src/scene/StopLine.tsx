import type { StopLineData } from '../recording/types'

/** Solid white bar across an approach's lanes, where the sim makes cars stop. */
export function StopLine({ data }: { data: StopLineData }) {
  return (
    <mesh position={[data.x, 0.025, -data.y]} rotation-y={data.heading} receiveShadow>
      <boxGeometry args={[0.4, 0.01, data.length]} />
      <meshStandardMaterial color="#f4f2ea" />
    </mesh>
  )
}
