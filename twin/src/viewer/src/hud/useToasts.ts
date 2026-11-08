import { useCallback, useEffect, useRef, useState } from 'react'
import type { HudEvent } from './events'

const SHOWN_MS = 6_000
const MAX_SHOWN = 4

/** A short stack of notices that go away by themselves (or when dismissed). */
export function useToasts() {
  const [toasts, setToasts] = useState<HudEvent[]>([])
  const timers = useRef(new Map<string, number>())

  const dismiss = useCallback((key: string) => {
    window.clearTimeout(timers.current.get(key))
    timers.current.delete(key)
    setToasts((current) => current.filter((t) => t.key !== key))
  }, [])

  const push = useCallback(
    (events: HudEvent[]) => {
      setToasts((current) => [...current, ...events].slice(-MAX_SHOWN))
      for (const e of events) timers.current.set(e.key, window.setTimeout(() => dismiss(e.key), SHOWN_MS))
    },
    [dismiss],
  )

  useEffect(() => {
    const live = timers.current
    return () => live.forEach((t) => window.clearTimeout(t))
  }, [])

  return { toasts, push, dismiss }
}
