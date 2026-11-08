import { ErrorNote } from '../components/ErrorNote'
import { Panel } from '../components/Panel'
import { usePolled } from '../usePolled'
import { getUnits } from './brainApi'

export function UnitList() {
  const { data, error } = usePolled(getUnits)
  return (
    <Panel title="The Twin's units">
      <ErrorNote error={error} />
      <ul className="rows">
        {data?.units.map((u) => (
          <li key={u.unit_id}>
            <strong>{u.unit_id}</strong> {u.unit_type}: {u.status}
            {u.incident_id ? `, ${u.incident_id}` : ''}
            {u.eta_seconds !== null ? `, about ${u.eta_seconds} s` : ''}
          </li>
        ))}
      </ul>
    </Panel>
  )
}
