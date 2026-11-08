/**
 * How much the scene asks of the renderer. A page cannot make a browser use the GPU, only ask for the
 * fast one (`powerPreference: 'high-performance'` in CityScene) and see what it got: when the browser draws
 * with the CPU (SwiftShader, llvmpipe: no hardware acceleration, or no usable driver) the scene drops to a
 * lighter profile, so it stays usable instead of crawling.
 */
export interface RenderQuality {
  mode: 'gpu' | 'software'
  /** the renderer string the browser reports, or null when WebGL is unavailable */
  renderer: string | null
  shadows: boolean
  shadowMapSize: number
  /** pixel ratio range handed to the canvas: [min, max] */
  dpr: [number, number]
  antialias: boolean
  /** flames and smoke puffs drawn per burning building */
  flames: number
  puffs: number
  /** `FIRE` labels are DOM elements that follow the camera: only drawn while few buildings burn */
  maxFireLabels: number
}

const SOFTWARE = /swiftshader|llvmpipe|softpipe|software|basic render|microsoft basic/i

export function isSoftwareRenderer(renderer: string | null): boolean {
  return renderer === null || SOFTWARE.test(renderer)
}

export function qualityFor(renderer: string | null): RenderQuality {
  if (isSoftwareRenderer(renderer)) {
    return { mode: 'software', renderer, shadows: false, shadowMapSize: 512, dpr: [1, 1], antialias: false, flames: 2, puffs: 2, maxFireLabels: 0 }
  }
  return { mode: 'gpu', renderer, shadows: true, shadowMapSize: 2048, dpr: [1, 1.5], antialias: true, flames: 6, puffs: 5, maxFireLabels: 6 }
}

/** Asks the browser which renderer a WebGL canvas gets (null if it gives none). */
export function probeRenderer(): string | null {
  try {
    const gl = document.createElement('canvas').getContext('webgl2') ?? document.createElement('canvas').getContext('webgl')
    if (!gl) return null
    const info = gl.getExtension('WEBGL_debug_renderer_info')
    const name = info ? String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL)) : String(gl.getParameter(gl.RENDERER))
    gl.getExtension('WEBGL_lose_context')?.loseContext()
    return name
  } catch {
    return null
  }
}

let cached: RenderQuality | null = null

/** The quality for this browser, worked out once. */
export function getRenderQuality(): RenderQuality {
  cached ??= qualityFor(probeRenderer())
  return cached
}
