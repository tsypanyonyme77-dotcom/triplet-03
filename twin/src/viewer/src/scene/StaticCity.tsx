import { useMemo } from 'react'
import type { CityMap } from '../recording/types'
import { blocks, bounds, streetProfile, streets } from './cityLayout'
import { Buildings } from './Buildings'
import { CityBlock } from './CityBlock'
import { Drains } from './Drains'
import { Crosswalk } from './Crosswalk'
import { Ground } from './Ground'
import { Kerbs } from './Kerbs'
import { ParkingBay } from './ParkingBay'
import { Station } from './Station'
import { StopLine } from './StopLine'
import { StreetSegment } from './StreetSegment'
import { PedestrianSignals } from './PedestrianSignals'
import { TrafficLights } from './TrafficLights'

/** Everything that does not move except the signal lamps: ground, streets, markings, parking bays, blocks, buildings, stations, lights, drains. */
export function StaticCity({
  map,
  selectedBuildingId,
  onSelectBuilding,
  selectedDrainId,
  onSelectDrain,
}: {
  map: CityMap
  selectedBuildingId: string | null
  onSelectBuilding: (id: string) => void
  selectedDrainId: string | null
  onSelectDrain: (id: string) => void
}) {
  const profile = useMemo(() => streetProfile(map), [map])
  const streetList = useMemo(() => streets(map), [map])
  const blockList = useMemo(() => blocks(map), [map])
  const area = useMemo(() => bounds(map), [map])

  return (
    <group>
      <Ground area={area} apron={profile.sidewalkOuter} />
      {streetList.map((s) => (
        <group key={`${s.a.id}-${s.b.id}`}>
          <StreetSegment street={s} halfWidth={profile.asphaltHalfWidth} />
          <Kerbs street={s} kerbOffset={profile.asphaltHalfWidth} inset={profile.sidewalkOuter} />
        </group>
      ))}
      {map.crosswalks.map((cw) => (
        <Crosswalk key={cw.id} data={cw} sidewalkWidth={map.profile.sidewalk_width_m} />
      ))}
      {map.parking.map((p) =>
        // recordings made before bays carried their size have no markings
        p.length && p.width ? (
          <ParkingBay key={p.id} x={p.x} y={p.y} heading={p.heading} length={p.length} width={p.width} />
        ) : null,
      )}
      {map.stop_lines.map((s) => (
        <StopLine key={`${s.approach[0]}-${s.approach[1]}`} data={s} />
      ))}
      {blockList.map((rect, i) => (
        <CityBlock key={i} rect={rect} inset={profile.sidewalkOuter} seed={i + 1} withBuildings={!map.buildings} />
      ))}
      {map.buildings && <Buildings buildings={map.buildings} selectedId={selectedBuildingId} onSelect={onSelectBuilding} />}
      {(map.stations ?? []).map((st) => (
        <Station key={st.id} data={st} />
      ))}
      <TrafficLights map={map} />
      <PedestrianSignals map={map} />
      <Drains zones={map.flood_zones ?? []} selectedId={selectedDrainId} onSelect={onSelectDrain} />
    </group>
  )
}
