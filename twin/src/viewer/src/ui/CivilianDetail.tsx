import { Crosshair, Percent, X } from 'lucide-react'
import type { Agent } from '../api/twinApi'
import { categoryIcon, KIND_ICON, ROLE_MARK_ICON, roleIcon } from '../icons/civilianIcons'
import { PlaceChip } from '../icons/PlaceChip'
import { TraitBars } from './TraitBars'
import { ago, percent } from './civilianView'

/** One person: who they are, home and duty place, what they chose and the runners-up. */
export function CivilianDetail({
  agent,
  now,
  following,
  onFollow,
}: {
  agent: Agent
  now: number
  following: boolean
  onFollow: () => void
}) {
  const Kind = KIND_ICON[agent.kind]
  const Role = roleIcon(agent.role)
  const Home = ROLE_MARK_ICON.home
  const DutyIcon = agent.duty ? categoryIcon(agent.duty.category) : ROLE_MARK_ICON.duty
  const dest = agent.destination
  return (
    <div className="civilian-detail">
      <div className="civilian-detail-head">
        <span className="civilian-who" title={`${agent.id}, ${agent.role}`}>
          <Kind size={18} />
          <Role size={18} />
          <b>{agent.id}</b>
        </span>
        <button
          type="button"
          className="round small"
          aria-label={following ? 'Stop following' : 'Follow with the camera'}
          title={following ? 'Stop following' : 'Follow with the camera'}
          onClick={onFollow}
        >
          {following ? <X size={16} /> : <Crosshair size={16} />}
        </button>
      </div>
      <TraitBars traits={agent.traits} />
      <div className="civilian-places">
        {agent.home && (
          <span title="Home">
            <Home size={14} /> {agent.home.name}
          </span>
        )}
        {agent.duty && (
          <span title={agent.role === 'worker' ? 'Work' : 'Duty'}>
            <DutyIcon size={14} /> {agent.duty.name}
          </span>
        )}
      </div>
      {dest && (
        <div className="civilian-choice">
          <span className="civilian-choice-main">
            <ROLE_MARK_ICON.destination size={16} />
            <PlaceChip category={dest.category} name={dest.name} size={16} />
            <span className="civilian-odds" title={`${percent(agent.probability)} likely, chosen ${ago(now, agent.decided_at_s)}`}>
              <Percent size={12} />
              {Math.round((agent.probability ?? 0) * 100)}
            </span>
          </span>
          {agent.alternatives.length > 0 && (
            <span className="civilian-alternatives" title="Passed over">
              <X size={12} />
              {agent.alternatives.map((a) => (
                <PlaceChip key={a.id} category={a.category} name={a.name} size={12} />
              ))}
            </span>
          )}
        </div>
      )}
    </div>
  )
}
