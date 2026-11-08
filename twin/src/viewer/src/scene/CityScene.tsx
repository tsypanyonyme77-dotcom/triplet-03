import { Canvas } from '@react-three/fiber'
import { Suspense } from 'react'
import { Traffic } from '../actors/Traffic'
import { ClockDriver } from '../playback/ClockDriver'
import { PlaybackProvider } from '../playback/ClockContext'
import type { PlaybackClock } from '../playback/clock'
import type { Recording } from '../recording/types'
import { AccidentMarkers } from './AccidentMarkers'
import { FloodWater } from './FloodWater'
import { Rain } from './Rain'
import { CallMarkers } from './CallMarkers'
import { CameraRig, type CameraFocus } from './CameraRig'
import type { CctvView } from './cctv'
import { FireEffects } from './FireEffects'
import { bounds } from './cityLayout'
import { Lighting } from './Lighting'
import { getRenderQuality } from './renderQuality'
import { BuildingNames } from './BuildingNames'
import { type Highlight, NO_HIGHLIGHT } from './placeLabels'
import { StaticCity } from './StaticCity'

export function CityScene({
  recording,
  clock,
  followId,
  followDistance,
  cctv,
  selectedBuildingId,
  onSelectBuilding,
  selectedDrainId,
  onSelectDrain,
  focus,
  highlight = NO_HIGHLIGHT,
}: {
  recording: Recording
  clock: PlaybackClock
  followId: string | null
  /** metres from whoever is followed: closer for a person than for a car */
  followDistance: number
  cctv: CctvView | null
  selectedBuildingId: string | null
  onSelectBuilding: (id: string | null) => void
  selectedDrainId: string | null
  onSelectDrain: (id: string | null) => void
  focus: CameraFocus | null
  /** places that matter to the selected person (destination, home, duty), drawn emphasised */
  highlight?: Highlight
}) {
  const quality = getRenderQuality()
  const area = bounds(recording.map)
  const center: [number, number, number] = [(area.minX + area.maxX) / 2, 0, -(area.minY + area.maxY) / 2]

  return (
    <Canvas
      shadows={quality.shadows}
      dpr={quality.dpr}
      gl={{ antialias: quality.antialias, powerPreference: 'high-performance' }}
      camera={{ position: [center[0] - 60, 90, center[2] + 120], fov: 45, near: 0.5, far: 2000 }}
      onPointerMissed={() => {
        onSelectBuilding(null)
        onSelectDrain(null)
      }}
    >
      <color attach="background" args={['#bcd7ea']} />
      <PlaybackProvider value={{ clock, recording }}>
        <ClockDriver />
        <Lighting center={center} shadows={quality.shadows} shadowMapSize={quality.shadowMapSize} />
        <StaticCity
          map={recording.map}
          selectedBuildingId={selectedBuildingId}
          onSelectBuilding={onSelectBuilding}
          selectedDrainId={selectedDrainId}
          onSelectDrain={onSelectDrain}
        />
        <FireEffects />
        <BuildingNames buildings={recording.map.buildings ?? []} places={recording.map.places ?? []} highlight={highlight} />
        <FloodWater />
        <Rain />
        <AccidentMarkers />
        <CallMarkers />
        <Suspense fallback={null}>
          <Traffic />
        </Suspense>
        <CameraRig center={center} followId={followId} followDistance={followDistance} cctv={cctv} focus={focus} />
      </PlaybackProvider>
    </Canvas>
  )
}
