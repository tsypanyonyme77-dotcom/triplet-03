import { getJson, postJson } from '../api'

export interface Sensor {
  sensor_id: string
  type: string
  zone_id: string
  sequence_no: number
  last_seen: string
  trust: string
  overruled: string | null
  cut_off: string | null
}

export const REASON = 'operator decision in the mock console'

export const getSensors = () => getJson<{ sensors: Sensor[] }>('/api/sensors')
export const setTrust = (sensorId: string, trust: boolean) => postJson<unknown>(`/api/sensors/${sensorId}/trust`, { trust, reason: REASON })
export const deviceAction = (sensorId: string, action: string) =>
  postJson<{ status: string; reason?: string }>(`/api/sensors/${sensorId}/actions`, { action, reason: REASON })
