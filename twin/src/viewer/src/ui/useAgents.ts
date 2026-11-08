import { type AgentsAnswer, getAgents } from '../api/twinApi'
import { usePolled } from '../timeline/usePolled'

const POLL_MS = 1_000

/** Everyone on the road and what they want to do, from the Twin once a second (live runs only). */
export function useAgents(enabled: boolean) {
  const polled = usePolled<AgentsAnswer | null>(enabled ? getAgents : noAgents, POLL_MS)
  return { answer: polled.data, problem: polled.error }
}

const noAgents = async () => null
