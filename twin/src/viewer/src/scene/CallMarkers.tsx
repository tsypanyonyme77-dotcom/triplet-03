import { Html } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useRef, useState } from 'react'
import { usePlayback } from '../playback/ClockContext'
import { frameAt } from '../playback/frameAt'

interface Caller {
  id: string
  kind: 'pedestrian' | 'driver'
  callId: string
  x: number
  y: number
}

/** A phone badge over everyone on the phone to the emergency number (frame.calls). A caller
 * stands still while calling, so the badge sits at their position when the call shows up. */
export function CallMarkers() {
  const { clock, recording } = usePlayback()
  const [callers, setCallers] = useState<Caller[]>([])
  const key = useRef('')

  useFrame(() => {
    const f = frameAt(recording.frames, recording.dt, clock.time)
    const calls = f.calls ?? []
    const k = calls.map((c) => c[2]).join(',')
    if (k === key.current) return
    key.current = k
    const where = new Map<string, [number, number]>()
    for (const e of [...f.cars, ...f.pedestrians]) where.set(e[0], [e[1], e[2]])
    setCallers(
      calls
        .filter(([id]) => where.has(id))
        .map(([id, kind, callId]) => ({ id, kind, callId, x: where.get(id)![0], y: where.get(id)![1] })),
    )
  })

  return (
    <>
      {callers.map((c) => (
        <Html key={c.callId} position={[c.x, c.kind === 'driver' ? 2.6 : 2.3, -c.y]} center>
          <div className="call-label" title={`${c.id} calling (${c.callId})`}>
            📞 {c.callId}
          </div>
        </Html>
      ))}
    </>
  )
}
