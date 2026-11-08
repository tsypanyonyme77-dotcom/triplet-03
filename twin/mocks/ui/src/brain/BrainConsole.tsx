import { ErrorNote } from '../components/ErrorNote'
import { EventFeed } from '../components/EventFeed'
import { Panel } from '../components/Panel'
import { ReadingStream } from '../components/ReadingStream'
import { usePolled } from '../usePolled'
import { getBoard } from './brainApi'
import { IncidentCard } from './IncidentCard'
import { ModeSwitch } from './ModeSwitch'
import { UnitList } from './UnitList'

export function BrainConsole() {
  const { data, error } = usePolled(getBoard)
  return (
    <div className="grid">
      <Panel title="Incidents">
        <ErrorNote error={error} />
        {data && <ModeSwitch auto={data.auto_dispatch} />}
        {data?.incidents.length === 0 && <p>No trusted report of an incident yet.</p>}
        {data?.incidents.map((incident) => (
          <IncidentCard key={incident.incident_id} incident={incident} actions={data.actions} />
        ))}
      </Panel>
      <UnitList />
      <ReadingStream title="Readings the Guardian vouched for" />
      <EventFeed />
    </div>
  )
}
