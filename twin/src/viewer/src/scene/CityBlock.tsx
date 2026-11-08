import { useMemo } from 'react'
import { Building, type BuildingSpec } from './Building'
import type { BlockRect } from './cityLayout'

const LAWN = '#8fb46a'
const ROW_DEPTH_M = 14
const BUILDING_WIDTH_M = 12

/** Small deterministic PRNG so the block looks the same on every load. */
function rng(seed: number): () => number {
  let s = seed
  return () => {
    s = (s * 1664525 + 1013904223) % 4294967296
    return s / 4294967296
  }
}

/** A lawn inset from the street centrelines, ringed by a row of buildings. With `withBuildings` off
 * (the map lists its own buildings) only the lawn is drawn. */
export function CityBlock({
  rect,
  inset,
  seed,
  withBuildings = true,
}: {
  rect: BlockRect
  inset: number
  seed: number
  withBuildings?: boolean
}) {
  const minX = rect.minX + inset
  const maxX = rect.maxX - inset
  const minY = rect.minY + inset
  const maxY = rect.maxY - inset

  const buildings = useMemo(() => {
    if (!withBuildings) return []
    const rand = rng(seed)
    const out: BuildingSpec[] = []
    const height = () => 8 + rand() * 22
    const along = (from: number, to: number) => {
      const n = Math.floor((to - from) / BUILDING_WIDTH_M)
      const w = (to - from) / n
      return Array.from({ length: n }, (_, i) => ({ c: from + w * (i + 0.5), w: w - 1 }))
    }
    for (const { c, w } of along(minX, maxX)) {
      out.push({ x: c, y: minY + ROW_DEPTH_M / 2, width: w, depth: ROW_DEPTH_M, height: height() })
      out.push({ x: c, y: maxY - ROW_DEPTH_M / 2, width: w, depth: ROW_DEPTH_M, height: height() })
    }
    for (const { c, w } of along(minY + ROW_DEPTH_M, maxY - ROW_DEPTH_M)) {
      out.push({ x: minX + ROW_DEPTH_M / 2, y: c, width: ROW_DEPTH_M, depth: w, height: height() })
      out.push({ x: maxX - ROW_DEPTH_M / 2, y: c, width: ROW_DEPTH_M, depth: w, height: height() })
    }
    return out
  }, [minX, maxX, minY, maxY, seed, withBuildings])

  return (
    <group>
      <mesh rotation-x={-Math.PI / 2} position={[(minX + maxX) / 2, 0.15, -(minY + maxY) / 2]} receiveShadow>
        <planeGeometry args={[maxX - minX, maxY - minY]} />
        <meshStandardMaterial color={LAWN} />
      </mesh>
      {buildings.map((b, i) => (
        <Building key={i} spec={b} />
      ))}
    </group>
  )
}
