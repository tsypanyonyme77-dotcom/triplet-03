import { useEffect, useState } from 'react'

export interface Polled<T> {
  data: T | null
  error: string | null
}

/** Asks `fetcher` every `everyMs`, one request at a time, and keeps the last answer through an error. */
export function usePolled<T>(fetcher: () => Promise<T>, everyMs = 1_000): Polled<T> {
  const [state, setState] = useState<Polled<T>>({ data: null, error: null })

  useEffect(() => {
    let waiting = false
    let stopped = false
    const tick = () => {
      if (waiting) return
      waiting = true
      fetcher()
        .then((data) => !stopped && setState({ data, error: null }))
        .catch((e: unknown) => !stopped && setState((s) => ({ data: s.data, error: String(e) })))
        .finally(() => {
          waiting = false
        })
    }
    tick()
    const id = window.setInterval(tick, everyMs)
    return () => {
      stopped = true
      window.clearInterval(id)
    }
  }, [fetcher, everyMs])

  return state
}
