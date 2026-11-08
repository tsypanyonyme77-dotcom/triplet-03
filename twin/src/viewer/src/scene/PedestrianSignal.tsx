import { useFrame } from '@react-three/fiber'
import { useRef } from 'react'
import type { MeshStandardMaterial } from 'three'
import { usePlayback } from '../playback/ClockContext'
import { frameAt } from '../playback/frameAt'
import { walkLamps } from './pedestrianSignal'

const POLE_HEIGHT_M = 2.4
const OFF = '#2a2a2a'
const RED = '#ff3b30'
const GREEN = '#2bd45b'

function setLamp(material: MeshStandardMaterial | null, lit: boolean, color: string) {
  material?.color.set(lit ? color : OFF)
  material?.emissive.set(lit ? color : '#000000')
}

/** One pedestrian signal head, facing across the road, following junction `nodeId`'s recorded state. */
export function PedestrianSignal({ nodeId, position, yaw }: { nodeId: number; position: [number, number, number]; yaw: number }) {
  const { clock, recording } = usePlayback()
  const red = useRef<MeshStandardMaterial>(null)
  const green = useRef<MeshStandardMaterial>(null)

  useFrame(() => {
    const lamps = walkLamps(frameAt(recording.frames, recording.dt, clock.time).walk?.[String(nodeId)], clock.time)
    setLamp(red.current, lamps.red, RED)
    setLamp(green.current, lamps.green, GREEN)
  })

  return (
    <group position={position} rotation-y={yaw}>
      <mesh position-y={POLE_HEIGHT_M / 2} castShadow>
        <cylinderGeometry args={[0.05, 0.06, POLE_HEIGHT_M, 8]} />
        <meshStandardMaterial color="#555" />
      </mesh>
      <mesh position-y={POLE_HEIGHT_M} castShadow>
        <boxGeometry args={[0.25, 0.5, 0.18]} />
        <meshStandardMaterial color="#222" />
      </mesh>
      <mesh position={[0, POLE_HEIGHT_M + 0.12, 0.1]}>
        <sphereGeometry args={[0.08, 10, 10]} />
        <meshStandardMaterial ref={red} emissiveIntensity={2} />
      </mesh>
      <mesh position={[0, POLE_HEIGHT_M - 0.12, 0.1]}>
        <sphereGeometry args={[0.08, 10, 10]} />
        <meshStandardMaterial ref={green} emissiveIntensity={2} />
      </mesh>
    </group>
  )
}
