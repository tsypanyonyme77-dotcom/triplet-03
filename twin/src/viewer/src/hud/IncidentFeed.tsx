import { Sparkles } from 'lucide-react'
import type { Incident } from './derive'
import { HELP_TEXT, INCIDENT_STYLE } from './kindStyle'

/** What is going wrong right now, one card each, with how help is going. Click a card to look at it. */
export function IncidentFeed({ incidents, onFocus }: { incidents: Incident[]; onFocus: (i: Incident) => void }) {
  if (incidents.length === 0) {
    return (
      <div className="hud-card incident-empty">
        <Sparkles size={16} /> All quiet in the city
      </div>
    )
  }
  return (
    <div className="incident-feed">
      {incidents.map((i) => {
        const { icon: Icon, tone } = INCIDENT_STYLE[i.kind]
        return (
          <button
            key={i.id}
            type="button"
            className={`hud-card incident ${i.help}`}
            style={{ '--tone': tone } as React.CSSProperties}
            onClick={() => onFocus(i)}
            title="Click to look at it"
          >
            <span className="incident-icon">
              <Icon size={22} />
            </span>
            <span className="incident-text">
              <strong>{i.title}</strong>
              <span>{i.detail}</span>
              <em>{HELP_TEXT[i.help]}</em>
            </span>
          </button>
        )
      })}
    </div>
  )
}
