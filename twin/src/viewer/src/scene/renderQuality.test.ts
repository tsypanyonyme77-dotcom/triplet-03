import { describe, expect, it } from 'vitest'
import { isSoftwareRenderer, qualityFor } from './renderQuality'

describe('isSoftwareRenderer', () => {
  it.each([
    'Google SwiftShader',
    'ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)), SwiftShader driver)',
    'llvmpipe (LLVM 19.1.7, 256 bits)',
    'Microsoft Basic Render Driver',
    'Mesa Software Renderer',
    null,
  ])('calls %s software', (name) => expect(isSoftwareRenderer(name)).toBe(true))

  it.each([
    'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)',
    'Mesa Intel(R) UHD Graphics 620 (KBL GT2)',
    'AMD Radeon RX 6600 (radeonsi, navi23, LLVM 19.1.7, DRM 3.59)',
    'Apple M2',
  ])('calls %s a GPU', (name) => expect(isSoftwareRenderer(name)).toBe(false))
})

describe('qualityFor', () => {
  it('uses shadows, sharp pixels and full fire effects on a GPU', () => {
    const q = qualityFor('NVIDIA GeForce RTX 3060')
    expect(q).toMatchObject({ mode: 'gpu', shadows: true, antialias: true })
    expect(q.flames).toBeGreaterThan(2)
  })

  it('drops shadows, extra pixels and most fire effects without one', () => {
    const q = qualityFor('llvmpipe')
    expect(q).toMatchObject({ mode: 'software', shadows: false, antialias: false, dpr: [1, 1], maxFireLabels: 0 })
    expect(q.flames).toBeLessThan(qualityFor('NVIDIA').flames)
  })
})
