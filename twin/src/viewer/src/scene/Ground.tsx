import type { BlockRect } from './cityLayout'

const GRASS = '#7fa35b'
const CONCRETE = '#c9c6bf'

/** Grass everywhere, with a concrete apron under the street grid (sidewalks show through). */
export function Ground({ area, apron }: { area: BlockRect; apron: number }) {
  const cx = (area.minX + area.maxX) / 2
  const cy = (area.minY + area.maxY) / 2
  const w = area.maxX - area.minX + apron * 2
  const h = area.maxY - area.minY + apron * 2
  return (
    <group>
      <mesh rotation-x={-Math.PI / 2} position={[cx, -0.02, -cy]} receiveShadow>
        <planeGeometry args={[w + 400, h + 400]} />
        <meshStandardMaterial color={GRASS} />
      </mesh>
      <mesh rotation-x={-Math.PI / 2} position={[cx, 0, -cy]} receiveShadow>
        <planeGeometry args={[w, h]} />
        <meshStandardMaterial color={CONCRETE} />
      </mesh>
    </group>
  )
}
