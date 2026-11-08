import { createContext, useContext, type ReactNode } from 'react'
import type { Recording } from '../recording/types'
import type { PlaybackClock } from './clock'

interface PlaybackValue {
  clock: PlaybackClock
  recording: Recording
}

const PlaybackContext = createContext<PlaybackValue | null>(null)

export function PlaybackProvider({ value, children }: { value: PlaybackValue; children: ReactNode }) {
  return <PlaybackContext.Provider value={value}>{children}</PlaybackContext.Provider>
}

export function usePlayback(): PlaybackValue {
  const value = useContext(PlaybackContext)
  if (!value) throw new Error('usePlayback must be used inside PlaybackProvider')
  return value
}
