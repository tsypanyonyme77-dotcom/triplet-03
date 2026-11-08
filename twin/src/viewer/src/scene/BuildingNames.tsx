import { useEffect, useMemo } from 'react'
import type { BuildingData, PlaceData } from '../recording/types'
import { type Highlight, type PlaceRole, roleOf } from './placeLabels'
import { makeWallTexture } from './wallTexture'
import { wallFaces } from './wallFaces'

/** One building's name, painted on all four of its walls. */
function BuildingName({ building, place, role }: { building: BuildingData; place: PlaceData; role: PlaceRole }) {
  const texture = useMemo(() => makeWallTexture(place.name, place.category, role), [place.name, place.category, role])
  useEffect(() => () => texture.dispose(), [texture])
  const faces = useMemo(() => wallFaces(building), [building])
  return (
    <group>
      {faces.map((f) => (
        <mesh key={f.side} position={f.position} rotation={[0, f.rotationY, 0]} renderOrder={2}>
          <planeGeometry args={[f.width, f.height]} />
          <meshBasicMaterial map={texture} transparent toneMapped={false} polygonOffset polygonOffsetFactor={-2} />
        </mesh>
      ))}
    </group>
  )
}

/**
 * Every place is a building, and its name is written on each of the building's walls (no floating
 * tags). The selected person's destination, home and duty place get a distinct plate.
 */
export function BuildingNames({ buildings, places, highlight }: { buildings: BuildingData[]; places: PlaceData[]; highlight: Highlight }) {
  const byBuilding = useMemo(() => new Map(places.filter((p) => p.building_id).map((p) => [p.building_id as string, p])), [places])
  return (
    <>
      {buildings.map((b) => {
        const place = byBuilding.get(b.id)
        return place ? <BuildingName key={b.id} building={b} place={place} role={roleOf(place, highlight)} /> : null
      })}
    </>
  )
}
