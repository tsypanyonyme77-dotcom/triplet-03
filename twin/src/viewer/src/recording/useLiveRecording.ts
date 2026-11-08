import { useEffect, useState } from 'react'
import { LiveStream, type LiveState } from './liveStream'

/** The Twin's live run as a growing recording, for as long as the component is mounted. */
export function useLiveRecording(): LiveState {
  const [state, setState] = useState<LiveState>({ status: 'connecting', problem: null })

  useEffect(() => {
    const stream = new LiveStream(setState)
    stream.start()
    return () => stream.stop()
  }, [])

  return state
}
