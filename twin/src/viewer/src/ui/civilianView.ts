import type { Agent } from '../api/twinApi'

const NATURAL = new Intl.Collator('en', { numeric: true })

/** Cars driving, pulling out or looking for a bay; pedestrians walking or waiting at a kerb. */
const MOVING = new Set(['driving', 'unparked', 'parking', 'walking', 'waiting'])

/** Someone with a destination who is on their way there now (not resting, undecided, injured or crashed). */
export function isHeading(a: Agent): boolean {
  return a.destination !== null && MOVING.has(a.status)
}

/** Only the people on their way, newest decision first, ties by id (ped2 before ped10). */
export function headingAgents(agents: Agent[]): Agent[] {
  return agents
    .filter(isHeading)
    .sort((a, b) => (b.decided_at_s ?? -1) - (a.decided_at_s ?? -1) || NATURAL.compare(a.id, b.id))
}

/** "just now", "12 s ago", "3 min ago": simulated time since the choice. */
export function ago(now: number, decidedAt: number | null): string {
  if (decidedAt === null) return 'not yet'
  const s = Math.max(0, Math.round(now - decidedAt))
  if (s < 3) return 'just now'
  return s < 90 ? `${s} s ago` : `${Math.round(s / 60)} min ago`
}

export const traitName = (key: string) => key.replace(/_/g, ' ')

/** The strongest traits, highest first (what makes this person who they are). */
export function topTraits(traits: Record<string, number>, n: number): [string, number][] {
  return Object.entries(traits)
    .sort((a, b) => b[1] - a[1])
    .slice(0, n)
}

/** Probability as a whole percent. */
export const percent = (p: number | null) => (p === null ? '' : `${Math.round(p * 100)}%`)
