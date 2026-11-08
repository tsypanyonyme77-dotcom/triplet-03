import type { HudSnapshot } from './derive'
import { UNIT_STATE_TEXT, UNIT_STYLE } from './kindStyle'

/** The emergency vehicles and what each is doing. Click one to follow it with the camera. */
export function UnitTray({
  units,
  followId,
  onFollow,
}: {
  units: HudSnapshot['units']
  followId: string | null
  onFollow: (id: string | null) => void
}) {
  if (units.length === 0) return null
  return (
    <div className="unit-tray">
      {units.map((u) => {
        const { icon: Icon, label, tone } = UNIT_STYLE[u.kind]
        return (
          <button
            key={u.id}
            type="button"
            className={`hud-card unit-chip ${u.state}${followId === u.id ? ' followed' : ''}`}
            style={{ '--tone': tone } as React.CSSProperties}
            title={`${label} ${u.id}: ${UNIT_STATE_TEXT[u.state]}. Click to follow.`}
            onClick={() => onFollow(followId === u.id ? null : u.id)}
          >
            <Icon size={18} />
            <span className="unit-state">{UNIT_STATE_TEXT[u.state]}</span>
          </button>
        )
      })}
    </div>
  )
}
