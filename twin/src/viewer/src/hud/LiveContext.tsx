import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { control, getScenarios, getStatus, runScenario, type BrainMode, type LiveStatus, type ScenarioStatus } from '../api/twinApi'

const POLL_MS = 1_000

interface LiveValue {
  /** null until the Twin has answered once */
  status: LiveStatus | null
  scenarios: ScenarioStatus | null
  /** the thing to tell the user: a stopped engine, or a Twin that does not answer; null when all is well */
  problem: string | null
  /** pause, resume, speed, reset, load: the live run's controls */
  run: (body: Record<string, unknown>) => Promise<void>
  startScenario: (id: string, brain: BrainMode) => Promise<void>
}

const Live = createContext<LiveValue | null>(null)

/** The live run's state, asked of the Twin once a second, shared by every part of the overlay that needs it. */
export function LiveProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<LiveStatus | null>(null)
  const [scenarios, setScenarios] = useState<ScenarioStatus | null>(null)
  const [problem, setProblem] = useState<string | null>(null)

  useEffect(() => {
    let waiting = false // one round at a time: a slow Twin must not use up the browser's connections
    const tick = () => {
      if (waiting) return
      waiting = true
      Promise.all([getStatus(), getScenarios().catch(() => null)])
        .then(([s, sc]) => {
          setStatus(s)
          setScenarios(sc)
          setProblem(null)
        })
        .catch((e: unknown) => setProblem(`The Twin is not answering (${String(e)}). Trying again…`))
        .finally(() => {
          waiting = false
        })
    }
    tick()
    const id = window.setInterval(tick, POLL_MS)
    return () => window.clearInterval(id)
  }, [])

  const run = useCallback(async (body: Record<string, unknown>) => {
    try {
      setStatus(await control(body))
      setProblem(null)
    } catch (e) {
      setProblem(String(e))
    }
  }, [])

  const startScenario = useCallback(async (id: string, brain: BrainMode) => {
    try {
      await runScenario(id, brain)
      setProblem(null)
    } catch (e) {
      setProblem(String(e))
    }
  }, [])

  const stopped = status?.engine_error ? `The engine stopped: ${status.engine_error}. Restart the run to bring it back.` : null
  const value = useMemo(
    () => ({ status, scenarios, problem: stopped ?? problem, run, startScenario }),
    [status, scenarios, stopped, problem, run, startScenario],
  )
  return <Live.Provider value={value}>{children}</Live.Provider>
}

/** The live run, or null when the viewer plays a recording. */
export function useLive(): LiveValue | null {
  return useContext(Live)
}
