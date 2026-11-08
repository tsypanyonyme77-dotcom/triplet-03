import type { HudSnapshot, UnitInfo } from './derive'

export type EventTone = 'alert' | 'info' | 'good'
export type EventIcon = 'fire' | 'accident' | 'siren' | 'arrived' | 'check'

/** Something worth a toast: what changed between two looks at the city. */
export interface HudEvent {
  key: string
  tone: EventTone
  icon: EventIcon
  title: string
  text: string
}

const UNIT_NAME: Record<UnitInfo['kind'], string> = { ambulance: 'Ambulance', police: 'Police car', fire: 'Fire truck' }

/** The events between `before` and `after`. Nothing for the very first look: what is already burning is not news. */
export function diffSnapshots(before: HudSnapshot | null, after: HudSnapshot, stamp: string): HudEvent[] {
  if (!before) return []
  const events: HudEvent[] = []
  const oldBurning = new Set(before.burning)
  const newBurning = after.burning.filter((b) => !oldBurning.has(b))
  const wasBurning = before.burning.length > 0
  if (newBurning.length > 0) {
    events.push({
      key: `${stamp}-fire`,
      tone: 'alert',
      icon: 'fire',
      title: wasBurning ? 'The fire is spreading!' : 'Fire!',
      text: wasBurning ? `${newBurning.join(', ')} caught fire` : `${newBurning[0]} is burning`,
    })
  }
  if (wasBurning && after.burning.length === 0) {
    events.push({ key: `${stamp}-out`, tone: 'good', icon: 'check', title: 'Fire is out', text: 'The firefighters did it' })
  }
  const oldIncidents = new Set(before.incidents.map((i) => i.id))
  for (const i of after.incidents) {
    if (i.id !== 'fires' && !oldIncidents.has(i.id)) {
      events.push({ key: `${stamp}-${i.id}`, tone: 'alert', icon: 'accident', title: i.title, text: i.detail })
    }
  }
  const oldIds = new Set(after.incidents.map((i) => i.id))
  for (const i of before.incidents) {
    if (i.id !== 'fires' && !oldIds.has(i.id)) {
      events.push({ key: `${stamp}-${i.id}-clear`, tone: 'good', icon: 'check', title: `${i.title} cleared`, text: 'The scene is clear' })
    }
  }
  const was = new Map(before.units.map((u) => [u.id, u.state]))
  for (const u of after.units) {
    const from = was.get(u.id)
    if (from === 'ready' && u.state === 'on_the_way') {
      events.push({ key: `${stamp}-${u.id}-go`, tone: 'info', icon: 'siren', title: `${UNIT_NAME[u.kind]} is on its way`, text: u.id })
    } else if (from === 'on_the_way' && u.state === 'working') {
      events.push({ key: `${stamp}-${u.id}-here`, tone: 'info', icon: 'arrived', title: `${UNIT_NAME[u.kind]} arrived`, text: u.id })
    }
  }
  return events
}
