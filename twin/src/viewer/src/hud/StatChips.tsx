import { Car, PersonStanding, Phone } from 'lucide-react'
import type { HudSnapshot } from './derive'

/** A few numbers about the city right now: the ones that say whether it is busy. */
export function StatChips({ snapshot }: { snapshot: HudSnapshot }) {
  return (
    <div className="stat-chips">
      <span className="hud-card chip" title="Cars on the road">
        <Car size={16} /> {snapshot.carsDriving}
      </span>
      <span className="hud-card chip" title="People out and about">
        <PersonStanding size={16} /> {snapshot.pedestrians}
      </span>
      <span className={`hud-card chip${snapshot.onThePhone ? ' hot' : ''}`} title="On the phone to the emergency number">
        <Phone size={16} /> {snapshot.onThePhone}
      </span>
    </div>
  )
}
