import { Cctv, Crosshair, Shuffle, X } from 'lucide-react'
import type { CctvView } from '../scene/cctv'
import { Drawer } from './Drawer'

/** Pick someone to follow, look through a traffic camera, or go back to the free camera. (Click an emergency
 * vehicle or an incident to look at it.) */
export function CameraDrawer({
  followId,
  carIds,
  pedIds,
  onFollow,
  cctvViews,
  cctv,
  onCctv,
  onClose,
}: {
  followId: string | null
  carIds: string[]
  pedIds: string[]
  onFollow: (id: string | null) => void
  cctvViews: CctvView[]
  cctv: CctvView | null
  onCctv: (id: string | null) => void
  onClose: () => void
}) {
  const pick = (ids: string[]) => ids.length > 0 && onFollow(ids[Math.floor(Math.random() * ids.length)])
  return (
    <Drawer title="Camera" onClose={onClose}>
      <p className="drawer-note">
        {followId ? (
          <>
            Following <b>{followId}</b>
          </>
        ) : cctv ? (
          <>
            Watching <b>{cctv.label}</b>
          </>
        ) : (
          'Free camera: drag to turn, scroll to zoom.'
        )}
      </p>
      <div className="button-row">
        <button type="button" className="big-button" onClick={() => pick(carIds)} disabled={carIds.length === 0}>
          <Shuffle size={16} /> Follow a car
        </button>
        <button type="button" className="big-button" onClick={() => pick(pedIds)} disabled={pedIds.length === 0}>
          <Shuffle size={16} /> Follow a person
        </button>
      </div>
      {cctvViews.length > 0 && (
        <>
          <p className="drawer-note">Traffic cameras</p>
          <div className="cctv-list">
            {cctvViews.map((v) => (
              <button key={v.id} type="button" className={`big-button quiet ${v.id === cctv?.id ? 'on' : ''}`} onClick={() => onCctv(v.id)}>
                <Cctv size={16} /> {v.label}
              </button>
            ))}
          </div>
        </>
      )}
      <button
        type="button"
        className="big-button quiet"
        onClick={() => {
          onFollow(null)
          onCctv(null)
        }}
        disabled={!followId && !cctv}
      >
        {followId || cctv ? <X size={16} /> : <Crosshair size={16} />} Free camera
      </button>
    </Drawer>
  )
}
