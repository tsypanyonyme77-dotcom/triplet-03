import type { LayerState } from '../api/twinApi'
import { layerLabel } from './timelineView'

/** Which layers answer right now: the timeline keeps going without them. */
export function LayerStatus({ layers }: { layers: Record<string, LayerState> }) {
  return (
    <ul className="layer-status">
      {Object.entries(layers).map(([layer, state]) => (
        <li key={layer} className={state.reachable ? 'up' : 'down'} title={state.error ?? undefined}>
          {layerLabel(layer).name}: {state.reachable ? 'connected' : 'not reachable'}
        </li>
      ))}
    </ul>
  )
}
