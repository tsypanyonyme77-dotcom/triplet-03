import { Html } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useRef, useState } from 'react'
import type { Mesh } from 'three'
import { usePlayback } from '../playback/ClockContext'
import { frameAt } from '../playback/frameAt'
import type { Frame } from '../recording/types'

type Active = Frame['accidents']

/** A pulsing red ring and a label on every accident (car-pedestrian or car-car) that is not cleared yet. */
export function AccidentMarkers() {
  const { clock, recording } = usePlayback()
  const [active, setActive] = useState<Active>([])
  const key = useRef('')

  useFrame(() => {
    const now = frameAt(recording.frames, recording.dt, clock.time).accidents
    const k = now.map((a) => a[0]).join(',')
    if (k !== key.current) {
      key.current = k
      setActive(now)
    }
  })

  return (
    <>
      {active.map(([id, x, y, carId, otherId, kind]) => (
        <group key={id} position={[x, 0, -y]}>
          <PulsingRing />
          <Html position={[0, 3, 0]} center>
            <div className="accident-label">
              ACCIDENT {id}: {accidentText(carId, otherId, kind)}
            </div>
          </Html>
        </group>
      ))}
    </>
  )
}

function accidentText(carId: string | null, otherId: string | null, kind: string): string {
  if (kind === 'flooded_car') return `${carId} stalled in floodwater, driver trapped`
  if (kind === 'trapped_pedestrian') return `${otherId} trapped in floodwater`
  return kind === 'car_car' ? `${carId} crashed into ${otherId}` : `${carId} hit ${otherId}`
}

function PulsingRing() {
  const ring = useRef<Mesh>(null)
  useFrame(({ clock }) => {
    const s = 1 + 0.25 * Math.sin(clock.elapsedTime * 6)
    ring.current?.scale.set(s, s, s)
  })
  return (
    <mesh ref={ring} rotation-x={-Math.PI / 2} position-y={0.05}>
      <ringGeometry args={[2.2, 2.8, 40]} />
      <meshBasicMaterial color="#ff2d2d" transparent opacity={0.85} />
    </mesh>
  )
}
