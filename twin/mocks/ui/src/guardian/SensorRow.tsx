import { ActionButton } from '../components/ActionButton'
import { deviceAction, setTrust, type Sensor } from './guardianApi'

export function SensorRow({ sensor }: { sensor: Sensor }) {
  const device = (action: string) => () => deviceAction(sensor.sensor_id, action).then((r) => [r.status, r.reason].filter(Boolean).join(': '))
  return (
    <tr className={sensor.trust}>
      <td>
        <strong>{sensor.sensor_id}</strong>
        <br />
        <small>
          {sensor.type}, {sensor.zone_id}
        </small>
      </td>
      <td>{sensor.sequence_no}</td>
      <td>
        {sensor.trust}
        {sensor.overruled ? ' (overruled)' : ''}
        {sensor.cut_off ? `, ${sensor.cut_off}d by the Twin` : ''}
      </td>
      <td className="actions">
        {sensor.overruled ? (
          <ActionButton label="Judge normally" run={() => setTrust(sensor.sensor_id, true).then(() => 'restored')} />
        ) : (
          <ActionButton label="Mark untrusted" run={() => setTrust(sensor.sensor_id, false).then(() => 'marked')} />
        )}
        {sensor.cut_off ? (
          <ActionButton label="Clear" run={device('clear_quarantine')} />
        ) : (
          <>
            <ActionButton label="Quarantine" run={device('quarantine_device')} />
            <ActionButton label="Isolate" run={device('isolate_sensor')} />
          </>
        )}
      </td>
    </tr>
  )
}
