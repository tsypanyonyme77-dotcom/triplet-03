import { useAnimations } from '@react-three/drei'
import { useFrame } from '@react-three/fiber'
import { useEffect, useRef, useState } from 'react'
import type { Group } from 'three'
import { usePlayback } from '../playback/ClockContext'
import { sampleEntity } from '../playback/sampleEntity'
import { dampAngle, headingToYaw, simToWorld } from '../scene/coords'
import { actorRegistry } from './actorRegistry'
import { GaitAnimator } from './gaitAnimator'
import { clipTimeScale, nextGait } from './locomotion'
import type { PersonLook } from './personLook'
import { useClonedScene } from './useClonedScene'

const TURN_TAU_S = 0.12 // smooths the turn between the 10 Hz recorded headings
const FALL_S = 0.4 // hit by a car: tip over to lying flat in this long

export function PedestrianActor({ id, look }: { id: string; look: PersonLook }) {
  const { clock, recording } = usePlayback()
  const { model } = look
  const { scene, animations } = useClonedScene(model.url, { material: model.outfitMaterial, color: look.outfit })
  const group = useRef<Group>(null)
  const body = useRef<Group>(null)
  const { actions, mixer } = useAnimations(animations, group)
  // drei's actions object is fixed for a given clip list; a person's model never changes
  const [animator] = useState(() => new GaitAnimator((name) => actions[name] ?? undefined, model.clips))
  const yaw = useRef<number | null>(null)
  const injuredSince = useRef<number | null>(null)

  useEffect(() => {
    const g = group.current
    if (!g) return
    actorRegistry.set(id, g)
    return () => {
      actorRegistry.delete(id)
    }
  }, [id])

  useFrame((_, delta) => {
    const g = group.current
    if (!g) return
    const s = sampleEntity(recording.frames, recording.dt, clock.time, id, (f) => f.pedestrians)
    g.visible = s !== undefined
    if (!s) {
      yaw.current = null
      return
    }
    g.position.set(...simToWorld(s.x, s.y))
    // the engine's heading is the body's facing (rate-limited, steady while standing:
    // simulation/app/ped_facing.py), so follow it even at a standstill, e.g. turning to the crosswalk
    const target = headingToYaw(s.heading, model.facing)
    yaw.current = yaw.current === null ? target : dampAngle(yaw.current, target, TURN_TAU_S, delta)
    g.rotation.y = yaw.current

    const injured = s.status === 'injured'
    if (!injured) injuredSince.current = null
    else if (injuredSince.current === null || injuredSince.current > clock.time) injuredSince.current = clock.time
    const fall = injured ? Math.min((clock.time - (injuredSince.current ?? clock.time)) / FALL_S, 1) : 0
    if (body.current) {
      // tips backwards onto the ground, face up, when hit by a car
      const eased = fall * fall * (3 - 2 * fall)
      body.current.rotation.x = -eased * (Math.PI / 2)
      body.current.position.y = eased * 0.25
    }

    const gait = injured ? 'idle' : nextGait(animator.gait, s.speed)
    animator.update(gait, clipTimeScale(gait, s.speed, model))
    // drei's useAnimations advances the mixer with real time; follow the playback rate instead,
    // and freeze the pose once the fall is over
    mixer.timeScale = clock.paused || fall >= 1 ? 0 : clock.rate
  })

  return (
    <group ref={group}>
      <group ref={body}>
        <primitive object={scene} scale={model.scale * look.height} />
      </group>
    </group>
  )
}
