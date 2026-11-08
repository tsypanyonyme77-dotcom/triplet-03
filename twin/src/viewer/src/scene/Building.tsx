import { Edges } from '@react-three/drei'
import type { ThreeEvent } from '@react-three/fiber'
import { useMemo } from 'react'
import { MeshStandardMaterial } from 'three'
import { buildingLook, FLOOR_M, GROUND_FLOOR_M, type BuildingLook } from './buildingStyle'
import { groundTexture, repeated, windowsTexture } from './facadeTextures'

export interface BuildingSpec {
  x: number
  y: number
  width: number
  depth: number
  height: number
  /** present for buildings the engine knows: they can be selected */
  id?: string
  /** the point on its street face (sim metres): where its shop's awning goes */
  front?: [number, number]
}

const ROOF = '#6d7175'
const PARAPET_M = 0.5
const CORNICE_M = 0.25
const AWNING_DEPTH_M = 1.3
const SELECTED = '#ffd400'

// BoxGeometry faces: +x, -x, +y, -y, +z, -z; the x faces are `depth` wide, the z faces `width`
function sideMaterials(look: BuildingLook, width: number, depth: number, height: number, ground: boolean): MeshStandardMaterial[] {
  const base = ground ? groundTexture(look) : windowsTexture(look)
  const up = ground ? 1 : height / (2 * FLOOR_M)
  const face = (along: number) => new MeshStandardMaterial({ map: repeated(base, along / (2 * look.bay), up), roughness: 0.85 })
  const xFace = face(depth)
  const zFace = face(width)
  const cap = new MeshStandardMaterial({ color: ground ? look.trim : ROOF, roughness: 0.9 })
  return [xFace, xFace, cap, cap, zFace, zFace]
}

/** Which face the street is on: the awning goes there. Returns [world offset x, world offset z, yaw, face length]. */
function streetFace(spec: BuildingSpec): [number, number, number, number] | null {
  if (!spec.front) return null
  const dx = spec.front[0] - spec.x
  const dy = spec.front[1] - spec.y
  if (Math.abs(dx) / spec.width > Math.abs(dy) / spec.depth) {
    return [Math.sign(dx) * (spec.width / 2 + AWNING_DEPTH_M / 2), 0, Math.PI / 2, spec.depth]
  }
  return [0, -Math.sign(dy) * (spec.depth / 2 + AWNING_DEPTH_M / 2), 0, spec.width]
}

/** A building: a ground floor with a shop or plain windows, upper floors of windows, a cornice, a parapet,
 * plant on the roof and a shop awning on its street face. Click it to select it (if it has an id). */
export function Building({ spec, selected = false, onSelect }: { spec: BuildingSpec; selected?: boolean; onSelect?: (id: string) => void }) {
  const { id, width, depth, height } = spec
  const look = useMemo(() => buildingLook(id ?? `${spec.x.toFixed(1)},${spec.y.toFixed(1)}`), [id, spec.x, spec.y])
  const ground = Math.min(GROUND_FLOOR_M, height * 0.4)
  const upper = height - ground
  const materials = useMemo(
    () => ({ ground: sideMaterials(look, width, depth, ground, true), upper: sideMaterials(look, width, depth, upper, false) }),
    [look, width, depth, ground, upper],
  )
  for (const m of [...materials.ground, ...materials.upper]) {
    m.emissive.set(selected ? SELECTED : '#000000')
    m.emissiveIntensity = selected ? 0.18 : 0
  }
  const awning = look.shop ? streetFace(spec) : null
  const units = Array.from({ length: look.roofUnits }, (_, i) => ({
    x: (i === 0 ? -0.2 : 0.22) * width,
    z: (i === 0 ? 0.15 : -0.2) * depth,
    size: 1.6 + i * 0.8,
  }))
  const click = id && onSelect ? (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation()
    onSelect(id)
  } : undefined

  return (
    <group position={[spec.x, 0, -spec.y]} onClick={click}>
      <mesh position-y={ground / 2} material={materials.ground} castShadow receiveShadow>
        <boxGeometry args={[width, ground, depth]} />
        {selected && <Edges color={SELECTED} lineWidth={2} />}
      </mesh>
      <mesh position-y={ground + upper / 2} material={materials.upper} castShadow receiveShadow>
        <boxGeometry args={[width, upper, depth]} />
        {selected && <Edges color={SELECTED} lineWidth={2} />}
      </mesh>
      <mesh position-y={ground + CORNICE_M / 2}>
        <boxGeometry args={[width + 0.3, CORNICE_M, depth + 0.3]} />
        <meshStandardMaterial color={look.trim} />
      </mesh>
      <mesh position-y={height + PARAPET_M / 2} castShadow>
        <boxGeometry args={[width + 0.2, PARAPET_M, depth + 0.2]} />
        <meshStandardMaterial color={look.trim} />
      </mesh>
      <mesh position-y={height + PARAPET_M + 0.01} rotation-x={-Math.PI / 2}>
        <planeGeometry args={[width - 0.4, depth - 0.4]} />
        <meshStandardMaterial color={ROOF} roughness={0.95} />
      </mesh>
      {units.map((u, i) => (
        <mesh key={i} position={[u.x, height + PARAPET_M + u.size / 2, u.z]} castShadow>
          <boxGeometry args={[u.size, u.size * 0.8, u.size * 1.2]} />
          <meshStandardMaterial color="#9aa0a6" metalness={0.3} roughness={0.6} />
        </mesh>
      ))}
      {awning && (
        <group position={[awning[0], ground - 0.7, awning[1]]} rotation-y={awning[2]}>
          <mesh rotation-x={0.28} castShadow>
            <boxGeometry args={[awning[3] * 0.85, 0.08, AWNING_DEPTH_M]} />
            <meshStandardMaterial color={look.awning} roughness={0.8} />
          </mesh>
        </group>
      )}
    </group>
  )
}
