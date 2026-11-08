import { useFrame } from '@react-three/fiber'
import { usePlayback } from './ClockContext'

/** Advances the playback clock once per rendered frame. Runs before actors (priority -1). */
export function ClockDriver() {
  const { clock } = usePlayback()
  useFrame((_, delta) => clock.advance(Math.min(delta, 0.1)), -1)
  return null
}
