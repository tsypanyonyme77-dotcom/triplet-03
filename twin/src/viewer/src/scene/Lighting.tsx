/** Soft sky light plus one shadow-casting sun covering the whole map. */
export function Lighting({
  center,
  shadows,
  shadowMapSize,
}: {
  center: [number, number, number]
  shadows: boolean
  shadowMapSize: number
}) {
  const [cx, , cz] = center
  return (
    <>
      <hemisphereLight args={['#ffffff', '#6b7a5a', 0.9]} />
      <directionalLight
        position={[cx + 60, 120, cz + 40]}
        intensity={2.2}
        castShadow={shadows}
        shadow-mapSize={[shadowMapSize, shadowMapSize]}
        shadow-camera-left={-130}
        shadow-camera-right={130}
        shadow-camera-top={130}
        shadow-camera-bottom={-130}
        shadow-camera-far={400}
        shadow-bias={-0.0005}
      >
        <object3D attach="target" position={[cx, 0, cz]} />
      </directionalLight>
    </>
  )
}
