import { Camera, Clapperboard, Settings, SlidersHorizontal, TriangleAlert, Users } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import type { PlaybackClock } from '../playback/clock'
import type { BuildingData, FloodZoneData, Recording } from '../recording/types'
import type { CctvView } from '../scene/cctv'
import { CameraDrawer } from './CameraDrawer'
import type { Incident } from './derive'
import { Dock } from './Dock'
import { IncidentFeed } from './IncidentFeed'
import { useLive } from './LiveContext'
import { RunBanner } from './RunBanner'
import { SandboxDrawer } from './SandboxDrawer'
import { ScenarioDrawer } from './ScenarioDrawer'
import { CctvBadge } from './CctvBadge'
import { DrainCard } from './DrainCard'
import { SelectionCard } from './SelectionCard'
import { SettingsDrawer } from './SettingsDrawer'
import { StatChips } from './StatChips'
import { StatusPill } from './StatusPill'
import { ToastStack } from './ToastStack'
import { Toolbar, type Tool } from './Toolbar'
import { UnitTray } from './UnitTray'
import { useHud } from './useHud'
import { useToasts } from './useToasts'
import './hud.css'

const LIVE_TOOLS: Tool[] = [
  { id: 'scenarios', label: 'Scenarios', icon: Clapperboard },
  { id: 'sandbox', label: 'City', icon: SlidersHorizontal },
  { id: 'camera', label: 'Camera', icon: Camera },
  { id: 'settings', label: 'Settings', icon: Settings },
]
const PEOPLE_TOOL: Tool = { id: 'people', label: 'People', icon: Users }
const RECORDING_TOOLS = LIVE_TOOLS.filter((t) => t.id === 'camera' || t.id === 'settings')

/**
 * Everything drawn over the 3D scene, as HTML. Top left: is it live and how far in. Top right: what is going
 * wrong, who is helping, and a few numbers. Left: the toolbar and its drawers. Bottom: the time dock. Top centre:
 * notices. The scene itself knows nothing about any of this.
 */
export function Hud({
  clock,
  recording,
  live,
  streamDown,
  followId,
  onFollow,
  cctvViews,
  cctv,
  onCctv,
  onFocus,
  selectedBuilding,
  onCloseBuilding,
  selectedDrain,
  onCloseDrain,
  carIds,
  pedIds,
  people,
}: {
  clock: PlaybackClock
  recording: Recording
  live: boolean
  streamDown: boolean
  followId: string | null
  onFollow: (id: string | null) => void
  cctvViews: CctvView[]
  cctv: CctvView | null
  onCctv: (id: string | null) => void
  onFocus: (x: number, y: number) => void
  selectedBuilding: BuildingData | undefined
  onCloseBuilding: () => void
  selectedDrain: FloodZoneData | undefined
  onCloseDrain: () => void
  carIds: string[]
  pedIds: string[]
  /** the People drawer's content (live runs with the decision model); the toolbar shows its button when given */
  people?: (close: () => void) => ReactNode
}) {
  const liveRun = useLive()
  const { toasts, push, dismiss } = useToasts()
  const snapshot = useHud(clock, recording, push)
  const [open, setOpen] = useState<string | null>(null)
  const toggle = (id: string) => setOpen((o) => (o === id ? null : id))
  const close = () => setOpen(null)
  const look = (i: Incident) => {
    onFollow(null)
    onCctv(null)
    onFocus(i.x, i.y)
  }

  return (
    <div className="hud">
      <div className="hud-top-left">
        <StatusPill clock={clock} streamDown={streamDown} />
      </div>

      <div className="hud-top-center">
        {liveRun && <RunBanner />}
        {liveRun?.problem && (
          <div className="hud-card problem-banner" role="alert">
            <TriangleAlert size={18} /> {liveRun.problem}
          </div>
        )}
        <ToastStack toasts={toasts} onDismiss={dismiss} />
      </div>

      {snapshot && (
        <div className="hud-top-right">
          <StatChips snapshot={snapshot} />
          <IncidentFeed incidents={snapshot.incidents} onFocus={look} />
          <UnitTray units={snapshot.units} followId={followId} onFollow={onFollow} />
        </div>
      )}

      <Toolbar tools={live ? (people ? [...LIVE_TOOLS, PEOPLE_TOOL] : LIVE_TOOLS) : RECORDING_TOOLS} open={open} onToggle={toggle} />
      <div className="hud-drawer-slot">
        {open === 'scenarios' && live && <ScenarioDrawer onClose={close} />}
        {open === 'sandbox' && liveRun?.status?.params && <SandboxDrawer key={liveRun.status.run_id} current={liveRun.status.params} onClose={close} />}
        {open === 'people' && live && people?.(close)}
        {open === 'camera' && <CameraDrawer followId={followId} carIds={carIds} pedIds={pedIds} onFollow={onFollow} cctvViews={cctvViews} cctv={cctv} onCctv={onCctv} onClose={close} />}
        {open === 'settings' && <SettingsDrawer live={live} onClose={close} />}
      </div>

      {cctv && <CctvBadge view={cctv} clock={clock} onExit={() => onCctv(null)} />}
      {selectedDrain && <DrainCard zone={selectedDrain} clock={clock} recording={recording} canFlood={live} onClose={onCloseDrain} />}
      {selectedBuilding && <SelectionCard building={selectedBuilding} canIgnite={live} onClose={onCloseBuilding} />}
      <Dock clock={clock} />
    </div>
  )
}
