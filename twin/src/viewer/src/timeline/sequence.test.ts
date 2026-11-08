import { describe, expect, it } from 'vitest'
import type { TimelineEvent } from '../api/twinApi'
import { laneCentre, sequenceRows, toRow } from './sequence'

const ev = (layer: string, kind: string, data: Record<string, unknown> = {}, routine = false): TimelineEvent => ({
  ts: '2026-11-08T10:00:00.000Z', layer, kind, message: kind, data, routine,
})

describe('the sequence diagram', () => {
  it('turns readings, verdicts and actuator calls into messages between layers', () => {
    expect(toRow(ev('twin', 'emergency_call_reading', { category: 'medical', call_id: 'call-0001' }))).toMatchObject({ from: 'twin', to: 'guardian', label: 'signed medical call call-0001' })
    expect(toRow(ev('guardian', 'verdict_issued', { trust: 'untrusted', verdict_id: 'v-1' }))).toMatchObject({ from: 'guardian', to: 'city_brain', failed: true })
    expect(toRow(ev('twin', 'actuator_call_received', { requesting_layer: 'city_brain', action: 'dispatch_unit' }))).toMatchObject({ from: 'city_brain', to: 'twin', label: 'dispatch_unit' })
    expect(toRow(ev('city_brain', 'actuator_called'))).toMatchObject({ from: 'twin', to: 'city_brain' })
    expect(toRow(ev('twin', 'delivery_failed', { target: 'guardian' }))).toMatchObject({ to: 'guardian', failed: true })
  })

  it('keeps everything else as a note on its own lifeline, the engine truth marked', () => {
    expect(toRow(ev('city_brain', 'incident_reported'))).toMatchObject({ from: 'city_brain', to: null, truth: false })
    expect(toRow(ev('twin', 'sim_incident'))).toMatchObject({ from: 'twin', to: null, truth: true })
  })

  it('shows routine chatter and ground truth only when asked', () => {
    const events = [ev('twin', 'reading_emitted', {}, true), ev('twin', 'sim_incident'), ev('city_brain', 'incident_reported')]
    expect(sequenceRows(events, { routine: false, truth: false }).map((r) => r.event.kind)).toEqual(['incident_reported'])
    expect(sequenceRows(events, { routine: true, truth: true })).toHaveLength(3)
  })

  it('puts the lifelines at the middle of each lane', () => {
    expect(laneCentre('twin')).toBeCloseTo(16.67, 1)
    expect(laneCentre('city_brain')).toBeCloseTo(83.33, 1)
  })
})
