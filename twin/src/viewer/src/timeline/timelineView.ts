export interface LayerLabel {
  name: string
  className: string
}

const LAYERS: Record<string, LayerLabel> = {
  twin: { name: 'Twin', className: 'layer-twin' },
  guardian: { name: 'Guardian', className: 'layer-guardian' },
  city_brain: { name: 'City Brain', className: 'layer-brain' },
}

export function layerLabel(layer: string): LayerLabel {
  return LAYERS[layer] ?? { name: layer, className: 'layer-other' }
}

/** "2026-11-08T14:03:21.123Z" -> "14:03:21.123" */
export function clockTime(ts: string): string {
  const match = /T(\d\d:\d\d:\d\d(?:\.\d+)?)/.exec(ts)
  return match ? match[1] : ts
}
