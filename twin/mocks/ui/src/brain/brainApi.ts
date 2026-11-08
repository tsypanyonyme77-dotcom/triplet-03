import { getJson, postJson } from '../api'

export interface Incident {
  incident_id: string
  zone_id: string
  type?: string
  status: string
  twin_phase?: string
  sources: string[]
  calls?: number
  confidence: number
  trust_ref: string
}

export interface Board {
  auto_dispatch: boolean
  sim_time_s: number
  actions: string[]
  incidents: Incident[]
}

export interface Unit {
  unit_id: string
  unit_type: string
  status: string
  incident_id: string | null
  eta_seconds: number | null
}

export interface ActionAnswer {
  result: { status: string; unit_id?: string; reason?: string }
}

export const getBoard = () => getJson<Board>('/api/incidents')
export const getUnits = () => getJson<{ units: Unit[] }>('/api/units')
export const setAuto = (auto: boolean) => postJson<unknown>('/api/mode', { auto })
export const act = (incidentId: string, action: string) => postJson<ActionAnswer>(`/api/incidents/${incidentId}/actions`, { action })
