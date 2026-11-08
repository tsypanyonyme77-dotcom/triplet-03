import { useFrame } from '@react-three/fiber'
import { useRef } from 'react'
import type { MeshStandardMaterial } from 'three'
import { usePlayback } from '../playback/ClockContext'
import { frameAt } from '../playback/frameAt'

const LAMP_COLORS: Record<string, string> = { green: '#2bd45b', yellow: '#ffc02e', red: '#ff3b30' }
const POLE_HEIGHT_M = 4

/**
 * One signal head facing one approach. Its lamp follows the recorded state of
 * light `nodeId` for traffic coming from `fromNodeId`.
 */
export function TrafficLight({
  nodeId,
  fromNodeId,
  position,
  yaw,
}: {
  nodeId: number
  fromNodeId: number
  position: [number, number, number]
  yaw: number
}) {
  const { clock, recording } = usePlayback()
  const lamp = useRef<MeshStandardMaterial>(null)

  useFrame(() => {
    const state = frameAt(recording.frames, recording.dt, clock.time).lights[String(nodeId)]?.[String(fromNodeId)]
    const color = LAMP_COLORS[state ?? 'green']
    lamp.current?.color.set(color)
    lamp.current?.emissive.set(color)
  })

  return (
    <group position={position} rotation-y={yaw}>
      <mesh position-y={POLE_HEIGHT_M / 2} castShadow>
        <cylinderGeometry args={[0.08, 0.1, POLE_HEIGHT_M, 8]} />
        <meshStandardMaterial color="#555" />
      </mesh>
      <mesh position-y={POLE_HEIGHT_M} castShadow>
        <boxGeometry args={[0.4, 0.9, 0.3]} />
        <meshStandardMaterial color="#222" />
      </mesh>
      <mesh position={[0, POLE_HEIGHT_M, 0.16]}>
        <sphereGeometry args={[0.14, 12, 12]} />
        <meshStandardMaterial ref={lamp} emissiveIntensity={2} />
      </mesh>
    </group>
  )
}
