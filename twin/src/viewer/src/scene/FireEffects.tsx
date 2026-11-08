import { Html } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useMemo, useRef, useState, type RefObject } from 'react'
import { ConeGeometry, MeshBasicMaterial, SphereGeometry, type Mesh } from 'three'
import { usePlayback } from '../playback/ClockContext'
import { activeFires } from '../playback/activeFires'
import { frameAt } from '../playback/frameAt'
import type { BuildingData } from '../recording/types'
import { getRenderQuality } from './renderQuality'

const SMOKE_RISE_M = 38

/** What every burning building shares: two geometries and the two flame colours. */
interface Shared {
  cone: ConeGeometry
  puff: SphereGeometry
  flame: [MeshBasicMaterial, MeshBasicMaterial]
}

/** Flames, a glow and a column of smoke on every burning building (frame.fires), as strong as the fire is.
 * The shapes are shared between buildings and their number follows the render quality (renderQuality.ts). */
export function FireEffects() {
  const { clock, recording } = usePlayback()
  const quality = getRenderQuality()
  const byId = useMemo(() => new Map((recording.map.buildings ?? []).map((b) => [b.id, b])), [recording.map])
  const shared = useMemo<Shared>(
    () => ({
      cone: new ConeGeometry(1.3, 3, 6),
      puff: new SphereGeometry(1, 8, 6),
      flame: [new MeshBasicMaterial({ color: '#ff5a1f' }), new MeshBasicMaterial({ color: '#ffb02e' })],
    }),
    [],
  )
  const strength = useRef(new Map<string, number>())
  const [burning, setBurning] = useState<string[]>([])
  const key = useRef('')

  useFrame(() => {
    const fires = activeFires(frameAt(recording.frames, recording.dt, clock.time))
    strength.current = new Map(fires.map((f) => [f.buildingId, f.strength]))
    const k = fires.map((f) => f.buildingId).join(',')
    if (k !== key.current) {
      key.current = k
      setBurning(fires.map((f) => f.buildingId))
    }
  })

  const labels = burning.length <= quality.maxFireLabels
  return (
    <>
      {burning.map((id) => {
        const building = byId.get(id)
        return building ? (
          <BurningBuilding
            key={id}
            building={building}
            strength={strength}
            shared={shared}
            flames={quality.flames}
            puffs={quality.puffs}
            label={labels}
          />
        ) : null
      })}
    </>
  )
}

/** Where flame `i` of `count` stands on the roof: spread over the footprint, the same every time. */
function flameSpot(b: BuildingData, i: number, count: number): [number, number] {
  const a = i * 2.399 // golden angle: an even scatter
  const r = Math.sqrt((i + 0.5) / count)
  return [Math.cos(a) * r * (b.width / 2 - 1), Math.sin(a) * r * (b.depth / 2 - 1)]
}

function BurningBuilding({
  building: b,
  strength,
  shared,
  flames: flameCount,
  puffs: puffCount,
  label,
}: {
  building: BuildingData
  strength: RefObject<Map<string, number>>
  shared: Shared
  flames: number
  puffs: number
  label: boolean
}) {
  const glow = useRef<MeshBasicMaterial>(null)
  const flames = useRef<(Mesh | null)[]>([])
  const puffs = useRef<(Mesh | null)[]>([])
  // smoke fades per puff, so each puff has its own material (the shapes are shared)
  const puffMaterials = useMemo(
    () => Array.from({ length: puffCount }, () => new MeshBasicMaterial({ color: '#555a60', transparent: true, opacity: 0, depthWrite: false })),
    [puffCount],
  )

  useFrame(({ clock }) => {
    const s = strength.current?.get(b.id) ?? 0
    const t = clock.elapsedTime
    if (glow.current) glow.current.opacity = s * (0.16 + 0.1 * Math.sin(t * 7))
    flames.current.forEach((m, i) => {
      if (!m) return
      const h = (0.3 + 1.7 * s) * (0.7 + 0.3 * Math.sin(t * 9 + i * 1.7))
      m.scale.set(1, Math.max(h, 0.01), 1)
      m.position.y = b.height + 1.5 * h
    })
    puffs.current.forEach((m, i) => {
      if (!m) return
      const p = (t * 0.16 + i / puffCount) % 1
      m.position.y = b.height + 2 + p * SMOKE_RISE_M
      m.scale.setScalar(2.5 + p * 8)
      puffMaterials[i].opacity = (1 - p) * 0.5 * s
    })
  })

  return (
    <group position={[b.x, 0, -b.y]}>
      <mesh position-y={b.height / 2}>
        <boxGeometry args={[b.width + 0.5, b.height + 0.5, b.depth + 0.5]} />
        <meshBasicMaterial ref={glow} color="#ff5a1f" transparent opacity={0} depthWrite={false} />
      </mesh>
      {Array.from({ length: flameCount }, (_, i) => {
        const [x, z] = flameSpot(b, i, flameCount)
        return (
          <mesh
            key={`f${i}`}
            ref={(m) => void (flames.current[i] = m)}
            position={[x, b.height, z]}
            geometry={shared.cone}
            material={shared.flame[i % 2]}
          />
        )
      })}
      {puffMaterials.map((material, i) => (
        <mesh
          key={`s${i}`}
          ref={(m) => void (puffs.current[i] = m)}
          position={[0, b.height + 2, 0]}
          geometry={shared.puff}
          material={material}
        />
      ))}
      {label && (
        <Html position={[0, b.height + 7, 0]} center>
          <div className="fire-label">FIRE</div>
        </Html>
      )}
    </group>
  )
}
