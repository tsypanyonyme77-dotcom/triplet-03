import { getReadings } from '../api'
import { readingSummary } from '../summaries'
import { usePolled } from '../usePolled'
import { ErrorNote } from './ErrorNote'
import { Panel } from './Panel'

export function ReadingStream({ title }: { title: string }) {
  const { data, error } = usePolled(getReadings)
  return (
    <Panel title={title}>
      <ErrorNote error={error} />
      {data?.items.length === 0 && <p>No readings yet.</p>}
      <ul className="rows">
        {data?.items.map(({ reading, verdict }) => (
          <li key={`${reading.sensor_id}-${reading.sequence_no}-${verdict.verdict_id}`} className={verdict.trust}>
            <strong>{reading.sensor_id}</strong> <small>#{reading.sequence_no}</small> {readingSummary(reading)}{' '}
            <span className="verdict">
              {verdict.trust} ({verdict.verdict_id})
            </span>
            {verdict.reasons.length > 0 && <small className="error"> {verdict.reasons.join('; ')}</small>}
          </li>
        ))}
      </ul>
    </Panel>
  )
}
