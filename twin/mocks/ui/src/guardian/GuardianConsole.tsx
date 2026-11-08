import { EventFeed } from '../components/EventFeed'
import { ReadingStream } from '../components/ReadingStream'
import { SensorTable } from './SensorTable'

export function GuardianConsole() {
  return (
    <div className="grid">
      <SensorTable />
      <ReadingStream title="Stream from the Twin, with verdicts" />
      <EventFeed />
    </div>
  )
}
