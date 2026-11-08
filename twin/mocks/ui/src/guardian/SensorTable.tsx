import { ErrorNote } from '../components/ErrorNote'
import { Panel } from '../components/Panel'
import { usePolled } from '../usePolled'
import { getSensors } from './guardianApi'
import { SensorRow } from './SensorRow'

export function SensorTable() {
  const { data, error } = usePolled(getSensors)
  return (
    <Panel title="Sensors">
      <ErrorNote error={error} />
      {data?.sensors.length === 0 && <p>No readings from the Twin yet.</p>}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Sensor</th>
              <th>Seq</th>
              <th>Trust</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {data?.sensors.map((s) => (
              <SensorRow key={s.sensor_id} sensor={s} />
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}
