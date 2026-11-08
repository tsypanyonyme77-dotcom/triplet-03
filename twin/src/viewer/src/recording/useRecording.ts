import { useEffect, useState } from 'react'
import type { Recording } from './types'

type State =
  | { status: 'loading' }
  | { status: 'ready'; recording: Recording }
  | { status: 'error'; message: string }

export function useRecording(url: string): State {
  const [state, setState] = useState<State>({ status: 'loading' })

  useEffect(() => {
    let cancelled = false
    fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`)
        return res.json() as Promise<Recording>
      })
      .then((recording) => {
        if (!cancelled) setState({ status: 'ready', recording })
      })
      .catch((err: unknown) => {
        if (!cancelled) setState({ status: 'error', message: String(err) })
      })
    return () => {
      cancelled = true
    }
  }, [url])

  return state
}
