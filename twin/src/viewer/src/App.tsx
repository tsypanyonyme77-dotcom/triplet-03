import { useEffect, useMemo, useState } from 'react'
import { PlaybackClock } from './playback/clock'
import type { Recording } from './recording/types'
import { useEntityIds } from './recording/useEntityIds'
import { useLiveRecording } from './recording/useLiveRecording'
import { useRecording } from './recording/useRecording'
import { Hud } from './hud/Hud'
import { LiveProvider } from './hud/LiveContext'
import type { CameraFocus } from './scene/CameraRig'
import { cctvViews } from './scene/cctv'
import { CityScene } from './scene/CityScene'
import { highlightOf } from './scene/placeLabels'
import { CivilianDrawer } from './ui/CivilianDrawer'
import { useAgents } from './ui/useAgents'
import { TimelinePage } from './timeline/TimelinePage'

const pickCars = (f: Recording['frames'][number]) => f.cars
const pickPeds = (f: Recording['frames'][number]) => f.pedestrians

const PERSON_FOLLOW_M = 7 // close enough to see who they are
const VEHICLE_FOLLOW_M = 14

function Viewer({ recording, live, streamDown = false }: { recording: Recording; live: boolean; streamDown?: boolean }) {
  const clock = useMemo(() => {
    if (!live) return new PlaybackClock(recording.frames.length * recording.dt)
    const frames = recording.frames
    return new PlaybackClock(() => [frames[0].t, frames[frames.length - 1].t], true)
  }, [recording, live])
  const [followId, setFollowIdRaw] = useState<string | null>(null)
  const [cctvId, setCctvIdRaw] = useState<string | null>(null)
  const views = useMemo(() => cctvViews(recording.map), [recording.map])
  const cctv = views.find((v) => v.id === cctvId) ?? null
  // the camera does one thing at a time: follow someone, look through a CCTV camera, or roam free
  const setFollowId = (id: string | null) => {
    setFollowIdRaw(id)
    if (id) setCctvIdRaw(null)
  }
  const setCctvId = (id: string | null) => {
    setCctvIdRaw(id)
    if (id) setFollowIdRaw(null)
  }
  const [focus, setFocus] = useState<CameraFocus | null>(null)
  const [selectedBuildingId, setSelectedBuildingId] = useState<string | null>(null)
  const selectedBuilding = recording.map.buildings?.find((b) => b.id === selectedBuildingId)
  const [selectedDrainId, setSelectedDrainId] = useState<string | null>(null)
  const selectedDrain = recording.map.flood_zones?.find((z) => z.id === selectedDrainId)
  // one thing selected at a time: a building or a street's drain
  const selectBuilding = (id: string | null) => {
    setSelectedBuildingId(id)
    if (id) setSelectedDrainId(null)
  }
  const selectDrain = (id: string | null) => {
    setSelectedDrainId(id)
    if (id) setSelectedBuildingId(null)
  }
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const { answer, problem } = useAgents(live)
  const agents = answer?.agents ?? null
  const highlight = useMemo(
    () => highlightOf(agents?.find((a) => a.id === selectedId)),
    [agents, selectedId],
  )
  const carIds = useEntityIds(recording, pickCars)
  const pedIds = useEntityIds(recording, pickPeds)
  const followDistance = followId && pedIds.includes(followId) ? PERSON_FOLLOW_M : VEHICLE_FOLLOW_M

  return (
    <>
      <CityScene
        recording={recording}
        clock={clock}
        followId={followId}
        followDistance={followDistance}
        cctv={cctv}
        highlight={highlight}
        selectedBuildingId={selectedBuildingId}
        onSelectBuilding={selectBuilding}
        selectedDrainId={selectedDrainId}
        onSelectDrain={selectDrain}
        focus={focus}
      />
      <Hud
        clock={clock}
        recording={recording}
        live={live}
        streamDown={streamDown}
        followId={followId}
        onFollow={setFollowId}
        cctvViews={views}
        cctv={cctv}
        onCctv={setCctvId}
        onFocus={(x, y) => setFocus((f) => ({ x, y, n: (f?.n ?? 0) + 1 }))}
        selectedBuilding={selectedBuilding}
        onCloseBuilding={() => setSelectedBuildingId(null)}
        selectedDrain={selectedDrain}
        onCloseDrain={() => setSelectedDrainId(null)}
        carIds={carIds}
        pedIds={pedIds}
        people={
          live
            ? (close) => (
                <CivilianDrawer
                  agents={agents}
                  now={answer?.sim_time_s ?? 0}
                  problem={problem}
                  selectedId={selectedId}
                  onSelect={setSelectedId}
                  followId={followId}
                  onFollow={setFollowId}
                  onClose={close}
                />
              )
            : undefined
        }
      />
    </>
  )
}

/** `?rec=<scenario>` plays a recording made with twin.world.record: `?rec=ped-hit` plays `recording-ped-hit.json`. */
function recordingUrl(): string {
  const rec = new URLSearchParams(window.location.search).get('rec')
  return rec && /^[a-z0-9-]+$/.test(rec) ? `/recording-${rec}.json` : '/recording.json'
}

function RecordedApp() {
  const state = useRecording(recordingUrl())
  if (state.status === 'loading') return <p className="message">Loading recording...</p>
  if (state.status === 'error') return <p className="message">Could not load the recording: {state.message}</p>
  return <Viewer recording={state.recording} live={false} />
}

/** The Twin's engine running now, streamed through the /twin proxy. */
function LiveApp() {
  const state = useLiveRecording()
  const [hasFrames, setHasFrames] = useState(false)
  const recording = state.status === 'ready' ? state.recording : null

  useEffect(() => {
    setHasFrames(false)
    if (!recording) return
    const id = window.setInterval(() => {
      if (recording.frames.length > 1) {
        setHasFrames(true)
        window.clearInterval(id)
      }
    }, 100)
    return () => window.clearInterval(id)
  }, [recording])

  const problem = state.status === 'connecting' ? state.problem : null
  return (
    <LiveProvider>
      {state.status === 'ready' && hasFrames ? (
        <Viewer key={state.runKey} recording={state.recording} live streamDown={!state.connected} />
      ) : (
        <p className="message">{problem ? `Waiting for the Twin, retrying (${problem})` : 'Connecting to the Twin...'}</p>
      )}
    </LiveProvider>
  )
}

export function App() {
  if (window.location.pathname === '/timeline') return <TimelinePage />
  return new URLSearchParams(window.location.search).has('rec') ? <RecordedApp /> : <LiveApp />
}
