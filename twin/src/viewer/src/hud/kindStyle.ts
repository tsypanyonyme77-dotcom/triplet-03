import { Ambulance, Car, Flame, PersonStanding, Siren, Truck, Waves, type LucideIcon } from 'lucide-react'
import type { Help, IncidentKind, UnitKind, UnitState } from './derive'

/** The look of each emergency vehicle and incident: an icon and the colour its card and chip take. */
export const UNIT_STYLE: Record<UnitKind, { icon: LucideIcon; label: string; tone: string }> = {
  ambulance: { icon: Ambulance, label: 'Ambulance', tone: 'var(--ambulance)' },
  police: { icon: Siren, label: 'Police car', tone: 'var(--police)' },
  fire: { icon: Truck, label: 'Fire truck', tone: 'var(--fire)' },
}

export const INCIDENT_STYLE: Record<IncidentKind, { icon: LucideIcon; tone: string }> = {
  fire: { icon: Flame, tone: 'var(--fire)' },
  pedestrian_hit: { icon: PersonStanding, tone: 'var(--ambulance)' },
  car_crash: { icon: Car, tone: 'var(--police)' },
  flood: { icon: Waves, tone: 'var(--water)' },
}

export const HELP_TEXT: Record<Help, string> = {
  waiting: 'Nobody is coming yet',
  on_the_way: 'Help is on the way',
  working: 'Help is working on it',
}

export const UNIT_STATE_TEXT: Record<UnitState, string> = {
  ready: 'Ready at the station',
  on_the_way: 'On its way',
  working: 'Working at the scene',
  returning: 'Heading home',
}

/** Scenario ids as people say them. */
export const SCENARIO_NAMES: Record<string, string> = {
  city: 'Busy city',
  'ped-hit': 'Pedestrian hit',
  'car-crash': 'Car crash',
  'building-fire': 'Building fire',
}
