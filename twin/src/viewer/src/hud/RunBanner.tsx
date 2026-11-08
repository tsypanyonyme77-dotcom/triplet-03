import { ListTree, Loader, PartyPopper, TriangleAlert, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useLive } from './LiveContext'

/** Top centre: a Test Book scenario is running, and then how it went. A pass is a small party. */
export function RunBanner() {
  const live = useLive()
  const current = live?.scenarios?.current ?? null
  const last = live?.scenarios?.last ?? null
  const [dismissed, setDismissed] = useState<string | null>(null)
  const finishedAt = last && 'finished_at' in last ? String((last as { finished_at?: string }).finished_at ?? last.id) : null

  useEffect(() => {
    if (current) setDismissed(null)
  }, [current])

  if (current) {
    return (
      <div className="hud-card run-banner running" role="status">
        <Loader size={18} className="spin" /> Running <b>{current.id.toUpperCase()}</b>: {current.name}…
        <a className="round ghost small" href="/timeline" target="_blank" rel="noreferrer" title="Watch it live, layer by layer">
          <ListTree size={14} />
        </a>
      </div>
    )
  }
  if (!last || finishedAt === dismissed) return null
  const missing = last.checks?.filter((c) => !c.seen) ?? []
  const pass = last.result === 'PASS'
  return (
    <div className={`hud-card run-banner ${pass ? 'pass' : 'fail'}`} role="status">
      {pass ? <PartyPopper size={20} /> : <TriangleAlert size={20} />}
      <span>
        <strong>
          {last.id.toUpperCase()} {pass ? 'passed!' : last.result === 'ERROR' ? 'could not finish' : 'did not pass'}
        </strong>
        {last.log && <span>log: logs/{last.log}</span>}
        {missing.length > 0 && <span>missing: {missing.map((c) => c.kind).join(', ')}</span>}
        {last.error && <span>{last.error}</span>}
        {last.run && (
          <a className="run-link" href={`/timeline?run=${last.run}`} target="_blank" rel="noreferrer" title="See what happened, layer by layer">
            <ListTree size={14} /> See the timeline
          </a>
        )}
      </span>
      <button type="button" aria-label="Dismiss" onClick={() => setDismissed(finishedAt)}>
        <X size={14} />
      </button>
    </div>
  )
}
