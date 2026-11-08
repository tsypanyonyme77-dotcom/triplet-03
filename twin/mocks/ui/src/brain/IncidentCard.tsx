import { ActionButton } from '../components/ActionButton'
import { incidentActions } from '../summaries'
import { act, type Incident } from './brainApi'

export function IncidentCard({ incident, actions }: { incident: Incident; actions: string[] }) {
  const run = (action: string) => () =>
    act(incident.incident_id, action).then(({ result }) => [result.status, result.unit_id ?? result.reason].filter(Boolean).join(' '))

  return (
    <article className="card">
      <h3>
        {incident.incident_id}: {incident.type ?? 'unknown'} <small>{incident.status}</small>
      </h3>
      <p>
        {incident.zone_id}, {incident.calls ?? 0} calls, sources {incident.sources.join(' + ')}, confidence {incident.confidence}, trusted by{' '}
        {incident.trust_ref}
        {incident.twin_phase ? `, the Twin says: ${incident.twin_phase}` : ''}
      </p>
      <div className="actions">
        {incidentActions(actions).map((a) => (
          <ActionButton key={a.id} label={a.label} run={run(a.id)} />
        ))}
      </div>
    </article>
  )
}
