import type { Agent } from '../api/twinApi'
import type { PlaceData } from '../recording/types'

/** What the selected person cares about: where they are going, where they live, where they work or study. */
export interface Highlight {
  destination: string | null
  home: string | null
  duty: string | null
}

export const NO_HIGHLIGHT: Highlight = { destination: null, home: null, duty: null }

export function highlightOf(agent: Agent | undefined): Highlight {
  if (!agent) return NO_HIGHLIGHT
  return { destination: agent.destination?.id ?? null, home: agent.home?.id ?? null, duty: agent.duty?.id ?? null }
}

export type PlaceRole = 'destination' | 'home' | 'duty' | 'plain'

export function roleOf(place: PlaceData, highlight: Highlight): PlaceRole {
  if (place.id === highlight.destination) return 'destination'
  if (place.id === highlight.home) return 'home'
  if (place.id === highlight.duty) return 'duty'
  return 'plain'
}

/** A colour per kind of place, so the map reads at a glance. */
export const CATEGORY_COLOR: Record<string, string> = {
  home: '#6b7280', office: '#2563eb', grocery: '#16a34a', restaurant: '#ea580c', cafe: '#a16207',
  school: '#7c3aed', gym: '#db2777', clinic: '#0891b2', pharmacy: '#0d9488', park: '#15803d',
  bank: '#4338ca', hospital: '#dc2626', mall: '#c026d3', transit_stop: '#0284c7', worship: '#92400e',
  market: '#b45309',
}

export const colorOf = (category: string) => CATEGORY_COLOR[category] ?? '#374151'
