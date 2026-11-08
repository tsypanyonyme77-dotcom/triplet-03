import { useState } from 'react'
import { getScenarios, runScenario, type BrainMode } from '../api/twinApi'
import { usePolled } from '../timeline/usePolled'

const POLL_MS = 1_000

/** One trigger, one log (R2): each button runs a Test Book scenario and names the log it wrote. */
export function ScenarioButtons() {
  const { data, error } = usePolled(getScenarios, POLL_MS)
  const [brain, setBrain] = useState<BrainMode>('auto')
  const [refused, setRefused] = useState<string | null>(null)
  const start = (id: string) => {
    setRefused(null)
    runScenario(id, brain).catch((e: unknown) => setRefused(String(e)))
  }
  const missing = data?.last?.checks?.filter((c) => !c.seen) ?? []

  return (
    <div className="scenario-buttons">
      {data?.scenarios.map((s) => (
        <button key={s.id} type="button" disabled={Boolean(data.current)} onClick={() => start(s.id)} title={s.name}>
          Run {s.id.toUpperCase()}: {s.name}
        </button>
      ))}
      <select value={brain} onChange={(e) => setBrain(e.target.value as BrainMode)} aria-label="Who decides in the mock City Brain">
        <option value="auto">Brain decides by itself</option>
        <option value="operator">Brain waits for its operator</option>
      </select>
      {data?.current && <span>Running {data.current.id.toUpperCase()}…</span>}
      {!data?.current && data?.last && (
        <span className={data.last.result === 'PASS' ? 'result-pass' : 'live-error'}>
          {data.last.id.toUpperCase()}: {data.last.result}
          {data.last.log ? ` · logs/${data.last.log}` : ''}
          {missing.length > 0 ? ` · missing ${missing.map((c) => c.kind).join(', ')}` : ''}
          {data.last.error ? ` · ${data.last.error}` : ''}
        </span>
      )}
      {(refused ?? error) && <span className="live-error">{refused ?? error}</span>}
    </div>
  )
}
