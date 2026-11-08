/** The HTTP calls and message shapes both consoles share. */
export interface Verdict {
  verdict_id: string
  trust: 'trusted' | 'untrusted'
  reasons: string[]
}

export interface Reading {
  sensor_id: string
  type: string
  zone_id: string
  timestamp: string
  sequence_no: number
  value: Record<string, unknown>
}

export interface ReadingItem {
  reading: Reading
  verdict: Verdict
}

export interface LayerEvent {
  ts: string
  kind: string
  message: string
}

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { signal: AbortSignal.timeout(5_000) })
  if (!res.ok) throw new Error(await errorText(res))
  return res.json()
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!res.ok) throw new Error(await errorText(res))
  return res.json()
}

async function errorText(res: Response): Promise<string> {
  const body = await res.text()
  try {
    return `${res.status}: ${JSON.parse(body).detail ?? body}`
  } catch {
    return `${res.status}: ${body}`
  }
}

export const getReadings = () => getJson<{ items: ReadingItem[] }>('/api/readings?limit=40')
export const getEvents = () => getJson<{ events: LayerEvent[] }>('/events?limit=40')
