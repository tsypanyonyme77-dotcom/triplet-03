import { useEffect, useRef } from 'react'
import { clockTime, layerLabel } from './timelineView'
import { LANES, laneCentre, type SequenceRow } from './sequence'

/** The three layers as lifelines, and what passed between them, oldest at the top. Sticks to the bottom
 * while new rows come in, unless the reader has scrolled up. */
export function SequenceDiagram({ rows }: { rows: SequenceRow[] }) {
  const box = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)

  useEffect(() => {
    const el = box.current
    if (el && pinned.current) el.scrollTop = el.scrollHeight
  }, [rows.length])

  return (
    <div className="sequence">
      <div className="sequence-head">
        <span />
        {LANES.map((lane) => (
          <span key={lane} className={`lane-head ${layerLabel(lane).className}`}>
            {layerLabel(lane).name}
          </span>
        ))}
      </div>
      <div
        className="sequence-body"
        ref={box}
        onScroll={(e) => {
          const el = e.currentTarget
          pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
        }}
      >
        {rows.map((row, i) => (
          <SequenceRowView key={`${row.event.ts}-${row.event.layer}-${row.event.kind}-${i}`} row={row} />
        ))}
      </div>
    </div>
  )
}

function SequenceRowView({ row }: { row: SequenceRow }) {
  const classes = ['seq-row', row.event.routine ? 'routine' : '', row.truth ? 'truth' : '', row.failed ? 'failed' : ''].join(' ')
  return (
    <div className={classes} title={`${row.event.layer} · ${row.event.kind}\n${row.event.message}`}>
      <time>{clockTime(row.event.ts)}</time>
      <div className="seq-lanes">
        {LANES.map((lane) => (
          <span key={lane} className={`lifeline ${layerLabel(lane).className}`} style={{ left: `${laneCentre(lane)}%` }} />
        ))}
        {row.to ? <Arrow row={row} to={row.to} /> : <Note row={row} />}
      </div>
    </div>
  )
}

function Arrow({ row, to }: { row: SequenceRow; to: (typeof LANES)[number] }) {
  const a = laneCentre(row.from)
  const b = laneCentre(to)
  const rightward = b > a
  return (
    <div className={`seq-arrow ${rightward ? 'right' : 'left'} ${layerLabel(row.from).className}`} style={{ left: `${Math.min(a, b)}%`, width: `${Math.abs(b - a)}%` }}>
      <span className="seq-label">{row.label}</span>
    </div>
  )
}

function Note({ row }: { row: SequenceRow }) {
  return (
    <div className={`seq-note ${layerLabel(row.from).className}`} style={{ left: `${laneCentre(row.from)}%` }}>
      <b>{row.event.kind.replace(/^sim_/, '')}</b> {row.label}
    </div>
  )
}
