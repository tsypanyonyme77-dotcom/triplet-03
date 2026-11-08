import { useCallback, useEffect, useState } from 'react'
import { getRun, getRuns, getTimeline, type ScenarioResult, type ScenarioRun, type Timeline } from '../api/twinApi'
import { ScenarioButtons } from '../ui/ScenarioButtons'
import { LayerStatus } from './LayerStatus'
import { SequenceDiagram } from './SequenceDiagram'
import { sequenceRows } from './sequence'
import { usePolled } from './usePolled'

const POLL_MS = 1_000
const LIVE_EVENTS = 800

function runFromUrl(): number | null {
  const run = Number(new URLSearchParams(window.location.search).get('run'))
  return Number.isInteger(run) && run > 0 ? run : null
}

/** The timeline screen (R3): the three layers as a sequence diagram, live, or one finished scenario run
 * (`/timeline?run=N`, linked from the run banner). Routine chatter and the engine's ground truth can be shown or hidden. */
export function TimelinePage() {
  const [run, setRun] = useState<number | null>(runFromUrl)
  const [routine, setRoutine] = useState(false)
  const [truth, setTruth] = useState(true)
  const runs = usePolled(useCallback(() => getRuns().then((r) => r.runs), []), 5_000)

  const choose = (next: number | null) => {
    setRun(next)
    window.history.replaceState(null, '', next ? `/timeline?run=${next}` : '/timeline')
  }

  return (
    <main className="timeline-page">
      <header>
        <h1>{run ? `Run ${run}` : 'Live timeline'}</h1>
        <a href="/">3D city</a>
        <select value={run ?? ''} onChange={(e) => choose(e.target.value ? Number(e.target.value) : null)} aria-label="Which timeline">
          <option value="">Live</option>
          {(runs.data ?? []).map((r: ScenarioResult) => (
            <option key={r.run} value={r.run}>
              Run {r.run}: {r.id.toUpperCase()} {r.result}
            </option>
          ))}
        </select>
        <label>
          <input type="checkbox" checked={routine} onChange={(e) => setRoutine(e.target.checked)} /> Routine events
        </label>
        <label>
          <input type="checkbox" checked={truth} onChange={(e) => setTruth(e.target.checked)} /> Engine ground truth
        </label>
      </header>
      {run ? <RunTimeline run={run} routine={routine} truth={truth} /> : <LiveTimeline routine={routine} truth={truth} />}
    </main>
  )
}

function LiveTimeline({ routine, truth }: { routine: boolean; truth: boolean }) {
  // routine chatter is always asked for, so switching it on shows what already happened
  const fetcher = useCallback(() => getTimeline(LIVE_EVENTS, true), [])
  const { data, error } = usePolled<Timeline>(fetcher, POLL_MS)
  const rows = data ? sequenceRows(data.events, { routine, truth }) : []
  return (
    <>
      <div className="timeline-bar">
        {data && <LayerStatus layers={data.layers} />}
        <ScenarioButtons />
      </div>
      {error && <p className="live-error">The Twin is not answering, retrying ({error})</p>}
      {rows.length === 0 && !error && <p>Nothing has happened yet. Run a scenario.</p>}
      <SequenceDiagram rows={rows} />
    </>
  )
}

function RunTimeline({ run, routine, truth }: { run: number; routine: boolean; truth: boolean }) {
  const [data, setData] = useState<ScenarioRun | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setData(null)
    setError(null)
    getRun(run)
      .then(setData)
      .catch((e: unknown) => setError(String(e)))
  }, [run])

  if (error) return <p className="live-error">Could not load run {run}: {error}</p>
  if (!data) return <p>Loading run {run}…</p>
  const missing = data.checks?.filter((c) => !c.seen) ?? []
  return (
    <>
      <div className="timeline-bar">
        <span className={data.result === 'PASS' ? 'result-pass' : 'live-error'}>
          {data.id.toUpperCase()} {data.name ?? ''}: {data.result}
        </span>
        {data.log && <span>log: logs/{data.log}</span>}
        {missing.length > 0 && <span className="live-error">missing: {missing.map((c) => `${c.layer}:${c.kind}`).join(', ')}</span>}
        {data.layers && <LayerStatus layers={data.layers} />}
      </div>
      <SequenceDiagram rows={sequenceRows(data.events, { routine, truth })} />
    </>
  )
}
