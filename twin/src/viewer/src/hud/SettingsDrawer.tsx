import { Cpu, ListTree, Zap } from 'lucide-react'
import { getRenderQuality } from '../scene/renderQuality'
import { Drawer } from './Drawer'

/** The few things nobody changes often: how the scene is drawn, and the timeline page. */
export function SettingsDrawer({
  live,
  onClose,
}: {
  live: boolean
  onClose: () => void
}) {
  const quality = getRenderQuality()
  return (
    <Drawer title="Settings" onClose={onClose}>
      <div className={`setting renderer ${quality.mode}`} title={quality.renderer ?? 'No WebGL renderer reported'}>
        {quality.mode === 'gpu' ? <Zap size={16} /> : <Cpu size={16} />}
        <span>
          {quality.mode === 'gpu' ? 'Drawn by the GPU' : 'Drawn by the CPU: shadows and some effects are off. Check chrome://gpu.'}
          {quality.renderer && <small>{quality.renderer}</small>}
        </span>
      </div>
      {live && (
        <a className="big-button quiet" href="/timeline" target="_blank" rel="noreferrer">
          <ListTree size={16} /> Open the three-layer timeline
        </a>
      )}
    </Drawer>
  )
}
