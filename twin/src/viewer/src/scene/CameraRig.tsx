import { OrbitControls } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useEffect, useRef } from 'react'
import { PerspectiveCamera, Vector3 } from 'three'
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib'
import { actorRegistry } from '../actors/actorRegistry'
import type { CctvView } from './cctv'

const tmp = new Vector3()
const ORBIT_FOV = 45
const CCTV_FOV = 65
const ZOOM_IN_S = 0.8 // starting to follow: glide in over this long, then the user's zoom is theirs
const FOLLOW_PITCH = 0.45 // rad above the horizon, when gliding in

/** A point to look at (sim metres). `n` changes on every request, so asking for the same place again works. */
export interface CameraFocus {
  x: number
  y: number
  n: number
}

/** Orbit camera. Following someone, it glides in to `followDistance` metres from them, then the orbit target
 * moves with them and the user's angle and zoom are kept. A CCTV view puts the camera on that camera's pole,
 * wide-angle and fixed; leaving it hands the orbit back, looking where the CCTV looked. A new `focus` moves
 * the view over a point. */
export function CameraRig({
  center,
  followId,
  followDistance,
  cctv,
  focus,
}: {
  center: [number, number, number]
  followId: string | null
  followDistance: number
  cctv: CctvView | null
  focus: CameraFocus | null
}) {
  const controls = useRef<OrbitControlsImpl>(null)
  const last = useRef<Vector3 | null>(null)
  const zoomFrom = useRef<{ t: number; from: Vector3 } | null>(null)

  useEffect(() => {
    const c = controls.current
    if (!c || !focus) return
    const dx = focus.x - c.target.x
    const dz = -focus.y - c.target.z
    c.target.x += dx
    c.target.z += dz
    c.object.position.x += dx
    c.object.position.z += dz
    c.update()
  }, [focus])

  useEffect(() => {
    const c = controls.current
    if (!c) return
    const camera = c.object as PerspectiveCamera
    camera.fov = cctv ? CCTV_FOV : ORBIT_FOV
    camera.updateProjectionMatrix()
    c.enabled = !cctv
    if (cctv) {
      camera.position.set(...cctv.eye)
      c.target.set(...cctv.look)
    }
    c.update()
  }, [cctv])

  useEffect(() => {
    last.current = null
    zoomFrom.current = null
  }, [followId])

  useFrame((_, delta) => {
    const c = controls.current
    if (!c || cctv) {
      if (c && cctv) c.object.lookAt(c.target)
      return
    }
    const actor = followId ? actorRegistry.get(followId) : undefined
    if (!actor) {
      last.current = null
      return
    }
    actor.getWorldPosition(tmp)
    if (last.current) {
      // move camera and target together so the user's chosen angle and zoom are kept
      const dx = tmp.x - last.current.x
      const dz = tmp.z - last.current.z
      c.target.x += dx
      c.target.z += dz
      c.object.position.x += dx
      c.object.position.z += dz
    } else {
      zoomFrom.current = { t: 0, from: c.object.position.clone().sub(c.target) }
      c.target.copy(tmp)
      c.object.position.copy(tmp).add(zoomFrom.current.from)
    }
    const zoom = zoomFrom.current
    if (zoom && zoom.t < ZOOM_IN_S) {
      // glide from where the camera was to close behind them, keeping the compass direction it looked from
      zoom.t = Math.min(ZOOM_IN_S, zoom.t + delta)
      const k = zoom.t / ZOOM_IN_S
      const ease = k * k * (3 - 2 * k)
      const flat = Math.hypot(zoom.from.x, zoom.from.z) || 1
      const want = new Vector3(
        (zoom.from.x / flat) * followDistance * Math.cos(FOLLOW_PITCH),
        followDistance * Math.sin(FOLLOW_PITCH),
        (zoom.from.z / flat) * followDistance * Math.cos(FOLLOW_PITCH),
      )
      c.object.position.copy(c.target).add(zoom.from.clone().lerp(want, ease))
    }
    last.current = tmp.clone()
    c.update()
  })

  return <OrbitControls ref={controls} target={center} maxPolarAngle={Math.PI / 2.1} makeDefault />
}
