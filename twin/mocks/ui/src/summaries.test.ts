import { describe, expect, it } from 'vitest'
import type { Reading } from './api'
import { incidentActions, readingSummary } from './summaries'

const reading = (type: string, value: Record<string, unknown>): Reading => ({
  sensor_id: 's',
  type,
  zone_id: 'zone-03',
  timestamp: 't',
  sequence_no: 1,
  value,
})

describe('readingSummary', () => {
  it('names what matters for each type', () => {
    expect(readingSummary(reading('emergency_call', { category: 'medical', call_id: 'call-1', incident_id: 'inc-1', caller_confidence: 0.8 }))).toBe(
      'medical call call-1 about inc-1 (confidence 0.8)',
    )
    expect(readingSummary(reading('traffic_camera', { vehicle_count: 3, avg_speed_kmh: 20, congestion_score: 0.5 }))).toBe(
      '3 vehicles, 20 km/h, congestion 0.5',
    )
    expect(readingSummary(reading('water_level', { level_m: 0.32, flow_rate_m3s: 1.5, pump_on: true }))).toBe(
      'water 0.32 m deep, draining 1.5 m³/s, pump on',
    )
    expect(readingSummary(reading('rainfall', { mm_per_hr: 120 }))).toBe('rain 120 mm/h')
  })

  it('tells smoke from a burning building and the air quality of a zone', () => {
    expect(readingSummary(reading('building_fire', { smoke_detected: true, building_id: 'bld-01-03', temp_c: 400, co2_ppm: 5000, incident_id: 'inc-1' }))).toBe(
      'smoke in bld-01-03: 400 C, CO2 5000 ppm, inc-1',
    )
    expect(readingSummary(reading('building_fire', { smoke_detected: false, building_id: 'bld-01-03' }))).toBe('smoke gone from bld-01-03')
    expect(readingSummary(reading('air_quality', { aqi: 120, pm25_ugm3: 42, pm10_ugm3: 75.6 }))).toBe('AQI 120, PM2.5 42, PM10 75.6')
  })

  it('shows an unknown type as it came', () => {
    expect(readingSummary(reading('power_load', { load_kw: 2 }))).toBe('{"load_kw":2}')
  })
})

describe('incidentActions', () => {
  it('orders the known actions and keeps unknown ones', () => {
    expect(incidentActions(['open_road', 'dispatch_police', 'new_one']).map((a) => a.label)).toEqual(['Dispatch police', 'Open the road', 'new_one'])
  })
})
