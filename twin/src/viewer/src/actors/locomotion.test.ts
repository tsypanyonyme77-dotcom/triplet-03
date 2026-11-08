import { describe, expect, it } from 'vitest'
import { clipTimeScale, nextGait } from './locomotion'
import { PEDESTRIAN_MODELS } from './modelCatalog'

describe('clipTimeScale', () => {
  for (const [key, model] of Object.entries(PEDESTRIAN_MODELS)) {
    it(`${key}: the feet keep up with the ground at every walking speed`, () => {
      // ground speed the clip shows = native speed x playback rate; it must match the body's speed
      for (const speed of [0.3, 0.4, 0.5, 0.7, 1.0, 1.4, 1.8]) {
        const shown = model.clipSpeed.walk * clipTimeScale('walk', speed, model)
        expect(Math.abs(shown - speed), `${speed} m/s`).toBeLessThan(0.1)
      }
    })

    it(`${key}: runs at the speed of the ground too`, () => {
      for (const speed of [2.4, 3.0, 3.6, 4.5]) {
        const shown = model.clipSpeed.run * clipTimeScale('run', speed, model)
        expect(Math.abs(shown - speed), `${speed} m/s`).toBeLessThan(0.1)
      }
    })
  }

  it('idles with a steady clip', () => {
    expect(clipTimeScale('idle', 0.05, PEDESTRIAN_MODELS.soldier)).toBe(1)
  })
})

describe('nextGait', () => {
  it('does not flip clips for a speed hovering around a threshold', () => {
    let gait = nextGait(undefined, 0.5) // walking
    const seen = new Set<string>()
    for (const speed of [0.2, 0.3, 0.2, 0.3, 0.2, 0.3, 0.2]) {
      gait = nextGait(gait, speed)
      seen.add(gait)
    }
    expect([...seen]).toEqual(['walk'])
  })
})
