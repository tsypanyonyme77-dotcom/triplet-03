/** Everything the viewer asks the Twin, through the /twin proxy (Vite in development, nginx in Docker). */
export const TWIN = '/twin'

export interface CityParams {
  cars: number
  pedestrians: number
  car_crash_risk: number
  ped_hit_risk: number
  fire_risk: number
  flood_risk: number
}

export interface LiveStatus {
  run_id: number
  scenario: string
  sim_time_s: number
  paused: boolean
  speed: number
  scenarios: string[]
  engine_error: string | null
  params: CityParams
}

export interface ScenarioCheck {
  layer: string
  kind: string
  meaning: string
  seen: boolean
}

export interface ScenarioResult {
  /** the run's number, for its timeline (GET /scenarios/runs/{run}); missing from older Twins */
  run?: number
  name?: string
  started_at?: string
  finished_at?: string
  id: string
  result: 'PASS' | 'FAIL' | 'ERROR'
  log: string | null
  checks?: ScenarioCheck[]
  error?: string
}

export interface ScenarioInfo {
  id: string
  name: string
}

export interface ScenarioStatus {
  scenarios: ScenarioInfo[]
  current: { run?: number; id: string; name: string; started_at?: string } | null
  last: ScenarioResult | null
}

export interface TimelineEvent {
  ts: string
  layer: string
  kind: string
  message: string
  data?: Record<string, unknown>
  /** periodic chatter (readings sent, notifications), present when asked for with routine=true */
  routine?: boolean
}

export interface LayerState {
  reachable: boolean
  error: string | null
}

export interface Timeline {
  layers: Record<string, LayerState>
  events: TimelineEvent[]
}

export type BrainMode = 'auto' | 'operator'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${TWIN}${path}`, { signal: AbortSignal.timeout(5_000), ...init })
  if (!res.ok) {
    const body = await res.text()
    let detail = body
    try {
      detail = JSON.parse(body).detail ?? body
    } catch {
      // not JSON: show the text as it is
    }
    throw new Error(`${res.status}: ${detail}`)
  }
  return res.json()
}

const post = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export const getStatus = () => request<LiveStatus>('/live/status')
export const control = (body: Record<string, unknown>) => post<LiveStatus>('/live/control', body)
export const getScenarios = () => request<ScenarioStatus>('/scenarios')
export const runScenario = (id: string, brain: BrainMode) => post<unknown>(`/scenarios/${id}/run`, { brain })
export const getTimeline = (limit = 500, routine = false, since = '') =>
  request<Timeline>(`/timeline?limit=${limit}&routine=${routine}${since ? `&since=${encodeURIComponent(since)}` : ''}`)

/** A finished scenario run with every event of the three layers. */
export interface ScenarioRun extends ScenarioResult {
  events: TimelineEvent[]
  layers?: Record<string, LayerState>
}

export const getRuns = () => request<{ runs: ScenarioResult[] }>('/scenarios/runs')
export const getRun = (run: number) => request<ScenarioRun>(`/scenarios/runs/${run}`)

export interface IgniteResult {
  status: 'ignited' | 'duplicate'
  fire_id: string
  building_id: string
}

/** The fire simulator: set a building on fire (the Twin answers `duplicate` if it already burns). */
export const igniteFire = (buildingId: string) => post<IgniteResult>('/simulators/ignite_fire', { building_id: buildingId })

export interface FloodResult {
  status: 'started' | 'duplicate'
  zone_id: string
  street: string
  pump_id: string
  rain_until_s: number
}

/** The flood simulator: block a street's drain and bring a downpour over it (`duplicate` if it already pours there). */
export const floodStreet = (zoneId: string) => post<FloodResult>('/simulators/flood_street', { zone_id: zoneId })

export interface PlaceRef {
  id: string
  name: string
  category: string
}

/** One pedestrian or driver, as the decision model sees them (GET /live/agents). */
export interface Agent {
  id: string
  kind: 'car' | 'pedestrian'
  /** cars: driving | parking | parked | unparked | crashed; pedestrians: walking | waiting | arrived | injured */
  status: string
  label: string
  role: string
  /** 0 to 1 each */
  traits: Record<string, number>
  home: PlaceRef | null
  duty: PlaceRef | null
  /** the place they stand at, if any */
  at: PlaceRef | null
  destination: (PlaceRef & { x: number; y: number }) | null
  decided_at_s: number | null
  probability: number | null
  alternatives: (PlaceRef & { p: number })[]
}

export interface AgentsAnswer {
  agents: Agent[]
  run_id: number
  sim_time_s: number
}

export const getAgents = () => request<AgentsAnswer>('/live/agents')
