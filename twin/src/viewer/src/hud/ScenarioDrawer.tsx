import { Bot, Car, Flame, Hand, Loader, PersonStanding, Rocket, type LucideIcon } from 'lucide-react'
import { useState } from 'react'
import type { BrainMode } from '../api/twinApi'
import { Drawer } from './Drawer'
import { useLive } from './LiveContext'

const LOOK: Record<string, { icon: LucideIcon; tone: string; blurb: string }> = {
  t1: { icon: PersonStanding, tone: 'var(--ambulance)', blurb: 'A careless driver, a distracted walker, a crosswalk.' },
  t2: { icon: Car, tone: 'var(--police)', blurb: 'A red light is run and two cars meet.' },
  t3: { icon: Flame, tone: 'var(--fire)', blurb: 'A building catches fire and spreads until help comes.' },
}

/** The Test Book's scenarios as cards. Each one is a trigger and a log, and says how it went when it is over. */
export function ScenarioDrawer({ onClose }: { onClose: () => void }) {
  const live = useLive()
  const [brain, setBrain] = useState<BrainMode>('auto')
  const running = live?.scenarios?.current ?? null

  return (
    <Drawer title="Scenarios" onClose={onClose}>
      <div className="segmented" role="group" aria-label="Who decides in the City Brain">
        <button type="button" className={brain === 'auto' ? 'on' : ''} onClick={() => setBrain('auto')} title="The mock City Brain decides by itself">
          <Bot size={16} /> Brain decides
        </button>
        <button type="button" className={brain === 'operator' ? 'on' : ''} onClick={() => setBrain('operator')} title="You decide, in the Brain's console">
          <Hand size={16} /> I decide
        </button>
      </div>
      <div className="scenario-cards">
        {live?.scenarios?.scenarios.map((s) => {
          const look = LOOK[s.id] ?? { icon: Rocket, tone: 'var(--accent)', blurb: '' }
          const Icon = running?.id === s.id ? Loader : look.icon
          return (
            <button
              key={s.id}
              type="button"
              className={`scenario-card${running?.id === s.id ? ' running' : ''}`}
              style={{ '--tone': look.tone } as React.CSSProperties}
              disabled={Boolean(running)}
              onClick={() => void live?.startScenario(s.id, brain)}
            >
              <span className="scenario-icon">
                <Icon size={22} />
              </span>
              <span>
                <strong>
                  {s.id.toUpperCase()} · {s.name}
                </strong>
                <span>{look.blurb}</span>
              </span>
            </button>
          )
        }) ?? <p className="drawer-note">Waiting for the Twin…</p>}
      </div>
    </Drawer>
  )
}
