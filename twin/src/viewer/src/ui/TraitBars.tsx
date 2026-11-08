import { traitIcon } from '../icons/civilianIcons'
import { traitName } from './civilianView'

/** One bar per trait, 0 to 1, each with its icon (hover for the name). */
export function TraitBars({ traits }: { traits: Record<string, number> }) {
  return (
    <div className="trait-bars">
      {Object.entries(traits).map(([name, value]) => {
        const Icon = traitIcon(name)
        return (
          <div key={name} className="trait" title={`${traitName(name)} ${value.toFixed(2)}`}>
            <Icon size={14} />
            <span className="trait-track">
              <span className="trait-fill" style={{ width: `${Math.round(value * 100)}%` }} />
            </span>
            <span className="trait-value">{value.toFixed(1)}</span>
          </div>
        )
      })}
    </div>
  )
}
