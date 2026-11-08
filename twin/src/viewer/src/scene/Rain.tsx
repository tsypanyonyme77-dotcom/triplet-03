import { useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import { BufferAttribute, BufferGeometry, type Points } from 'three'
import { usePlayback } from '../playback/ClockContext'
import { frameAt } from '../playback/frameAt'
import type { FloodZoneData } from '../recording/types'
import { rainOver } from './drainView'

const DROPS = 1500 // per street
const HEAVY_MM_H = 120 // every drop falls at this intensity and above
const TOP_M = 35
const FALL_MS = 14
const BEYOND_DIP_M = 16 // the cloud reaches this far past the dip along the street ...
const ACROSS_M = 34 // ... and is this wide

/** Falling rain over every street it rains on, as many drops as that street's intensity (mm/h) calls for. */
export function Rain() {
  const { recording } = usePlayback()
  return (
    <>
      {(recording.map.flood_zones ?? []).map((zone) => (
        <StreetRain key={zone.id} zone={zone} />
      ))}
    </>
  )
}

function StreetRain({ zone }: { zone: FloodZoneData }) {
  const { clock, recording } = usePlayback()
  const points = useRef<Points>(null)
  const geometry = useMemo(() => {
    const along = zone.half_length_m + BEYOND_DIP_M
    const pos = new Float32Array(DROPS * 3)
    for (let i = 0; i < DROPS; i++) {
      pos[i * 3] = (Math.random() * 2 - 1) * along
      pos[i * 3 + 1] = Math.random() * TOP_M
      pos[i * 3 + 2] = (Math.random() - 0.5) * ACROSS_M
    }
    const g = new BufferGeometry()
    g.setAttribute('position', new BufferAttribute(pos, 3))
    g.setDrawRange(0, 0)
    return g
  }, [zone])

  useFrame((_, delta) => {
    const rain = rainOver(frameAt(recording.frames, recording.dt, clock.time), zone.id)
    const count = Math.round(DROPS * Math.min(1, rain / HEAVY_MM_H))
    geometry.setDrawRange(0, count)
    if (points.current) points.current.visible = count > 0
    if (count === 0) return
    const position = geometry.getAttribute('position') as BufferAttribute
    const arr = position.array as Float32Array
    const fall = FALL_MS * Math.min(delta, 0.1)
    for (let i = 0; i < count; i++) {
      const y = arr[i * 3 + 1] - fall
      arr[i * 3 + 1] = y < 0 ? y + TOP_M : y
    }
    position.needsUpdate = true
  })

  return (
    <group position={[zone.x, 0, -zone.y]} rotation-y={zone.heading}>
      <points ref={points} geometry={geometry} frustumCulled={false}>
        <pointsMaterial color="#c6d8e8" size={0.18} transparent opacity={0.75} depthWrite={false} />
      </points>
    </group>
  )
}
