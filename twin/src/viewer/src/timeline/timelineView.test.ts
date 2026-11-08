import { describe, expect, it } from 'vitest'
import { clockTime, layerLabel } from './timelineView'

describe('the timeline view', () => {
  it('names known layers and keeps unknown ones readable', () => {
    expect(layerLabel('city_brain').name).toBe('City Brain')
    expect(layerLabel('partner_x')).toEqual({ name: 'partner_x', className: 'layer-other' })
  })

  it('shows only the time of a timestamp', () => {
    expect(clockTime('2026-11-08T14:03:21.123Z')).toBe('14:03:21.123')
    expect(clockTime('not a time')).toBe('not a time')
  })
})
