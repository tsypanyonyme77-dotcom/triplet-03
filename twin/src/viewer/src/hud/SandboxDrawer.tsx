import { Building2, Car, CloudRain, Flame, PersonStanding, Siren, TrafficCone, type LucideIcon } from 'lucide-react'
import { useState } from 'react'
import type { CityParams } from '../api/twinApi'
import { Drawer } from './Drawer'
import { useLive } from './LiveContext'

const FIELDS: { key: keyof CityParams; label: string; hint: string; icon: LucideIcon; min: number; max: number; step: number }[] = [
  { key: 'cars', label: 'Cars', hint: 'How many cars drive around', icon: Car, min: 0, max: 47, step: 1 },
  { key: 'pedestrians', label: 'People', hint: 'How many people walk', icon: PersonStanding, min: 0, max: 100, step: 1 },
  { key: 'car_crash_risk', label: 'Red-light runners', hint: 'Share of drivers who run red lights', icon: Siren, min: 0, max: 1, step: 0.05 },
  { key: 'ped_hit_risk', label: 'Careless road users', hint: 'Share of drivers who do not yield and walkers who ignore signals', icon: TrafficCone, min: 0, max: 1, step: 0.05 },
  { key: 'fire_risk', label: 'Fire-prone buildings', hint: 'Share of buildings that catch fire on their own', icon: Flame, min: 0, max: 1, step: 0.05 },
  { key: 'flood_risk', label: 'Flood-prone streets', hint: 'Share of streets whose drain blocks in a downpour', icon: CloudRain, min: 0, max: 1, step: 0.05 },
]

const show = (key: keyof CityParams, value: number): string => (key === 'cars' || key === 'pedestrians' ? String(value) : `${Math.round(value * 100)}%`)

/** The default city's size and how much goes wrong in it. Applied by starting a new run. */
export function SandboxDrawer({ current, onClose }: { current: CityParams; onClose: () => void }) {
  const live = useLive()
  const [params, setParams] = useState<CityParams>(current)
  return (
    <Drawer title="City sandbox" onClose={onClose}>
      <form
        className="sandbox"
        onSubmit={(e) => {
          e.preventDefault()
          void live?.run({ action: 'load', scenario: 'city', params })
        }}
      >
        {FIELDS.map(({ key, label, hint, icon: Icon, min, max, step }) => (
          <label key={key} title={hint}>
            <span className="slider-head">
              <Icon size={16} /> {label}
              <b>{show(key, params[key])}</b>
            </span>
            <input type="range" min={min} max={max} step={step} value={params[key]} onChange={(e) => setParams({ ...params, [key]: Number(e.target.value) })} />
          </label>
        ))}
        <button type="submit" className="big-button">
          <Building2 size={18} /> Start this city
        </button>
      </form>
    </Drawer>
  )
}
