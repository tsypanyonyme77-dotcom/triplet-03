import { Users } from 'lucide-react'
import { useMemo } from 'react'
import type { Agent } from '../api/twinApi'
import { Drawer } from '../hud/Drawer'
import { CivilianDetail } from './CivilianDetail'
import { CivilianRow } from './CivilianRow'
import { headingAgents } from './civilianView'
import './civilians.css'

/**
 * The people on their way right now and where each is heading, in the HUD's drawer style.
 * Click one for their traits and what they chose over what.
 */
export function CivilianDrawer({
  agents,
  now,
  problem,
  selectedId,
  onSelect,
  followId,
  onFollow,
  onClose,
}: {
  agents: Agent[] | null
  now: number
  problem: string | null
  selectedId: string | null
  onSelect: (id: string | null) => void
  followId: string | null
  onFollow: (id: string | null) => void
  onClose: () => void
}) {
  const heading = useMemo(() => headingAgents(agents ?? []), [agents])
  return (
    <Drawer title={`People on the move${agents ? ` (${heading.length})` : ''}`} onClose={onClose}>
      {problem && !agents && <p className="drawer-note">Waiting for the Twin.</p>}
      {agents && agents.length === 0 && (
        <p className="drawer-note">
          <Users size={14} /> The decision model is off, so people pick random places.
        </p>
      )}
      {agents && agents.length > 0 && heading.length === 0 && <p className="drawer-note">Everyone is resting or deciding.</p>}
      <div className="civilian-list">
        {heading.map((a) => (
          <div key={a.id}>
            <CivilianRow agent={a} selected={a.id === selectedId} onSelect={() => onSelect(a.id === selectedId ? null : a.id)} />
            {a.id === selectedId && (
              <CivilianDetail agent={a} now={now} following={followId === a.id} onFollow={() => onFollow(followId === a.id ? null : a.id)} />
            )}
          </div>
        ))}
      </div>
    </Drawer>
  )
}
