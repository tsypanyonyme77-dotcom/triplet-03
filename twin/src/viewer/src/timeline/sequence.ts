import type { TimelineEvent } from '../api/twinApi'

export const LANES = ['twin', 'guardian', 'city_brain'] as const
export type Lane = (typeof LANES)[number]

/** One row of the sequence diagram: a message from one layer to another, or a note on one layer's lifeline. */
export interface SequenceRow {
  event: TimelineEvent
  from: Lane
  /** null: a note on `from`'s own lifeline */
  to: Lane | null
  label: string
  failed: boolean
  truth: boolean
}

const isLane = (x: unknown): x is Lane => typeof x === 'string' && (LANES as readonly string[]).includes(x)

/** Who said what to whom, worked out from each layer's own events. */
export function toRow(event: TimelineEvent): SequenceRow {
  const layer: Lane = isLane(event.layer) ? event.layer : 'twin'
  const data = event.data ?? {}
  const note = (label = event.message): SequenceRow => ({ event, from: layer, to: null, label, failed: false, truth: event.kind.startsWith('sim_') })
  const message = (from: Lane, to: Lane, label: string, failed = false): SequenceRow => ({ event, from, to, label, failed, truth: false })

  switch (`${layer}:${event.kind}`) {
    case 'twin:emergency_call_reading':
      return message('twin', 'guardian', `signed ${String(data.category ?? '')} call ${String(data.call_id ?? '')}`.replace(/\s+/g, ' '))
    case 'twin:reading_emitted':
      return message('twin', 'guardian', `${String(data.count ?? '')} readings`.trim())
    case 'twin:brain_notified':
      return message('twin', 'city_brain', 'new readings available')
    case 'twin:delivery_failed':
      return isLane(data.target) ? message('twin', data.target, 'delivery failed', true) : note()
    case 'twin:actuator_call_received':
      return isLane(data.requesting_layer) ? message(data.requesting_layer, 'twin', String(data.action ?? 'actuator call')) : note()
    case 'twin:actuator_rejected':
      return note(`refused: ${event.message}`)
    case 'guardian:verdict_issued':
      return message('guardian', 'city_brain', String(data.trust ?? 'verdict') + ` (${String(data.verdict_id ?? '')})`, data.trust === 'untrusted')
    case 'guardian:actuator_called':
    case 'city_brain:actuator_called':
      return message('twin', layer, `answer: ${event.message}`)
    case 'guardian:actuator_failed':
    case 'city_brain:actuator_failed':
      return message(layer, 'twin', event.message, true)
    default:
      return note()
  }
}

export interface SequenceFilter {
  routine: boolean
  truth: boolean
}

/** Oldest first, as a sequence diagram reads: routine chatter and the engine's ground truth only when asked for. */
export function sequenceRows(events: TimelineEvent[], filter: SequenceFilter): SequenceRow[] {
  return events
    .filter((e) => (filter.routine || !e.routine) && (filter.truth || !e.kind.startsWith('sim_')))
    .map(toRow)
}

/** Where a lane's lifeline is, as a percentage of the lanes' width. */
export function laneCentre(lane: Lane): number {
  return ((LANES.indexOf(lane) + 0.5) / LANES.length) * 100
}
