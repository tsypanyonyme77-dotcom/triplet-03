import { Html } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useMemo, useRef, useState } from 'react'
import { BufferAttribute, BufferGeometry } from 'three'
import { usePlayback } from '../playback/ClockContext'
import { frameAt } from '../playback/frameAt'
import type { FloodZoneData } from '../recording/types'
import { waterGrid } from './waterSurface'

const ALONG = 48
const ACROSS = 12
const REDRAW_M = 0.002 // redraw the surface when the depth changed by this much

/** The water in each flood zone of the map, as deep as the current frame says, with its depth and pump. */
export function FloodWater() {
  const { recording } = usePlayback()
  return (
    <>
      {(recording.map.flood_zones ?? []).map((zone) => (
        <ZoneWater key={zone.id} zone={zone} />
      ))}
    </>
  )
}

function ZoneWater({ zone }: { zone: FloodZoneData }) {
  const { clock, recording } = usePlayback()
  const drawn = useRef(-1)
  const [label, setLabel] = useState<{ depth: number; pump: boolean } | null>(null)
  const geometry = useMemo(() => {
    const g = new BufferGeometry()
    g.setAttribute('position', new BufferAttribute(waterGrid(zone, 0, ALONG, ACROSS), 3))
    const index: number[] = []
    const row = ACROSS + 1
    for (let i = 0; i < ALONG; i++) {
      for (let j = 0; j < ACROSS; j++) {
        const a = i * row + j
        index.push(a, a + 1, a + row, a + 1, a + row + 1, a + row)
      }
    }
    g.setIndex(index)
    g.computeVertexNormals()
    return g
  }, [zone])

  useFrame(() => {
    const entry = frameAt(recording.frames, recording.dt, clock.time).flood?.find((f) => f[0] === zone.id)
    const depth = entry ? entry[1] : 0
    const pump = entry ? entry[2] : false
    if (Math.abs(depth - drawn.current) >= REDRAW_M || (depth === 0 && drawn.current !== 0)) {
      drawn.current = depth
      const position = geometry.getAttribute('position') as BufferAttribute
      position.array.set(waterGrid(zone, depth, ALONG, ACROSS))
      position.needsUpdate = true
      geometry.computeVertexNormals()
    }
    const shown = depth > 0.01 ? { depth: Math.round(depth * 100) / 100, pump } : null
    if (shown?.depth !== label?.depth || shown?.pump !== label?.pump) setLabel(shown)
  })

  return (
    <group position={[zone.x, 0, -zone.y]} rotation-y={zone.heading}>
      <mesh geometry={geometry} receiveShadow>
        <meshStandardMaterial color="#3f7fae" transparent opacity={0.72} roughness={0.15} metalness={0.1} depthWrite={false} />
      </mesh>
      {label && (
        <Html position={[0, 3.5, 0]} center>
          <div className="accident-label flood-label">
            WATER {label.depth.toFixed(2)} m{label.pump ? ' · pump on' : ''}
          </div>
        </Html>
      )}
    </group>
  )
}
