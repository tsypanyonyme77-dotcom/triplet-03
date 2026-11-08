import { useEffect, useState } from 'react'
import { getJson } from './api'
import { BrainConsole } from './brain/BrainConsole'
import { GuardianConsole } from './guardian/GuardianConsole'

const TITLES: Record<string, string> = { city_brain: 'Mock City Brain', guardian: 'Mock Guardian' }

/** Both mocks serve this bundle; the mock it came from says which console to show. */
export function App() {
  const [layer, setLayer] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getJson<{ layer: string }>('/api/identity')
      .then(({ layer }) => {
        setLayer(layer)
        document.title = TITLES[layer] ?? layer
      })
      .catch((e: unknown) => setError(String(e)))
  }, [])

  if (error) return <p className="error page">Could not reach the mock: {error}</p>
  if (!layer) return <p className="page">Loading…</p>
  return (
    <main className="page">
      <h1>{TITLES[layer] ?? layer}</h1>
      <p className="muted">A stand-in for the real layer, so the Twin can run alone.</p>
      {layer === 'guardian' ? <GuardianConsole /> : <BrainConsole />}
    </main>
  )
}
