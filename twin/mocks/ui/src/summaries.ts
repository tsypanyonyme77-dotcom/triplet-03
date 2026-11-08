import type { Reading } from './api'

/** One line for a reading in the stream, naming what matters for its type. */
export function readingSummary(reading: Reading): string {
  const v = reading.value
  switch (reading.type) {
    case 'emergency_call':
      return `${v.category} call ${v.call_id} about ${v.incident_id} (confidence ${v.caller_confidence})`
    case 'cctv_anomaly':
      return `${v.anomaly_type} seen (confidence ${v.confidence})${v.incident_id ? `, ${v.incident_id}` : ''}`
    case 'building_fire':
      return v.smoke_detected
        ? `smoke in ${v.building_id}: ${v.temp_c} C, CO2 ${v.co2_ppm} ppm, ${v.incident_id}`
        : `smoke gone from ${v.building_id}`
    case 'air_quality':
      return `AQI ${v.aqi}, PM2.5 ${v.pm25_ugm3}, PM10 ${v.pm10_ugm3}`
    case 'traffic_camera':
      return `${v.vehicle_count} vehicles, ${v.avg_speed_kmh} km/h, congestion ${v.congestion_score}`
    case 'water_level':
      return `water ${v.level_m} m deep, draining ${v.flow_rate_m3s} m³/s${v.pump_on ? ', pump on' : ''}`
    case 'rainfall':
      return `rain ${v.mm_per_hr} mm/h`
    default:
      return JSON.stringify(v)
  }
}

export interface IncidentAction {
  id: string
  label: string
}

const LABELS: Record<string, string> = {
  dispatch_ambulance: 'Dispatch ambulance',
  dispatch_police: 'Dispatch police',
  dispatch_fire: 'Dispatch fire truck',
  close_road: 'Close the road',
  open_road: 'Open the road',
  start_pump: 'Start the drainage pump',
  stop_pump: 'Stop the drainage pump',
}

/** The Brain's actions in a sensible order, each with a label; one the console does not know keeps its id. */
export function incidentActions(actions: string[]): IncidentAction[] {
  const known = Object.keys(LABELS).filter((id) => actions.includes(id))
  const other = actions.filter((id) => !(id in LABELS))
  return [...known, ...other].map((id) => ({ id, label: LABELS[id] ?? id }))
}
