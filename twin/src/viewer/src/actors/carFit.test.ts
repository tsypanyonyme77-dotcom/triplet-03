import { describe, expect, it } from 'vitest'
import { fitCar } from './carFit'
import { AMBULANCE_MODEL, CAR_MODELS } from './modelCatalog'

const BODY = { length: 4.5, width: 2.0 }

describe('fitCar', () => {
  it('draws every model inside the sim body, touching it on one side', () => {
    for (const model of [...CAR_MODELS, AMBULANCE_MODEL]) {
      const fit = fitCar(model, BODY)
      expect(fit.length).toBeLessThanOrEqual(BODY.length + 1e-9)
      expect(fit.width).toBeLessThanOrEqual(BODY.width + 1e-9)
      expect(Math.max(fit.length / BODY.length, fit.width / BODY.width)).toBeCloseTo(1)
    }
  })

  it('centres the model on the body even when its file is not centred', () => {
    const model = { ...CAR_MODELS[0], size: { length: 2.0, width: 1.0, centerZ: 0.1 } }
    const fit = fitCar(model, BODY)
    expect(fit.scale).toBeCloseTo(2.0) // width-limited: 1.0 x 2 = 2.0 m
    expect(fit.offsetZ).toBeCloseTo(-0.2) // its centre, 0.1 x 2 ahead, moved back onto the body centre
  })
})
