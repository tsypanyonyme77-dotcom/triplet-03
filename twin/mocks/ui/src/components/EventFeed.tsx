import { getEvents } from '../api'
import { usePolled } from '../usePolled'
import { ErrorNote } from './ErrorNote'
import { Panel } from './Panel'

export function EventFeed() {
  const { data, error } = usePolled(getEvents)
  const events = data ? [...data.events].reverse() : []
  return (
    <Panel title="What this layer did">
      <ErrorNote error={error} />
      <ul className="rows">
        {events.map((e, i) => (
          <li key={`${e.ts}-${e.kind}-${i}`}>
            <small>{e.ts.slice(11, 23)}</small> {e.message}
          </li>
        ))}
      </ul>
    </Panel>
  )
}
