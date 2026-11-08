const FLASH_HZ = 1.5

export interface WalkLamps {
  red: boolean
  green: boolean
}

/** Which lamps of a pedestrian signal are lit: steady green on walk, blinking green while people finish crossing, else red. */
export function walkLamps(state: string | undefined, timeS: number): WalkLamps {
  if (state === 'walk') return { red: false, green: true }
  if (state === 'flash') return { red: false, green: Math.floor(timeS * FLASH_HZ * 2) % 2 === 0 }
  return { red: true, green: false }
}
