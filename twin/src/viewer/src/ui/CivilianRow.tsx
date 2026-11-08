import { ArrowRight } from 'lucide-react'
import type { Agent } from '../api/twinApi'
import { KIND_ICON, roleIcon } from '../icons/civilianIcons'
import { PlaceChip } from '../icons/PlaceChip'

/** One person on their way: what they are (vehicle, role), an arrow, and where they are heading. */
export function CivilianRow({ agent, selected, onSelect }: { agent: Agent; selected: boolean; onSelect: () => void }) {
  const Kind = KIND_ICON[agent.kind]
  const Role = roleIcon(agent.role)
  const dest = agent.destination
  return (
    <button
      type="button"
      className={`hud-card civilian-row${selected ? ' selected' : ''}`}
      title={`${agent.id}, ${agent.role}${agent.status === 'waiting' ? ', waiting to cross' : ''}`}
      onClick={onSelect}
    >
      <span className="civilian-who">
        <Kind size={16} />
        <Role size={16} />
      </span>
      <ArrowRight size={14} className="civilian-arrow" />
      {dest && <PlaceChip category={dest.category} name={dest.name} />}
    </button>
  )
}
