import { AnimationClip, AnimationMixer, Object3D, VectorKeyframeTrack } from 'three'
import { describe, expect, it } from 'vitest'
import { GaitAnimator } from './gaitAnimator'
import type { Gait } from './locomotion'

const DT = 1 / 60
const CLIPS = { idle: 'Idle', walk: 'Walk', run: 'Run' }

/**
 * A rig whose every clip holds `target.position.x` at 1 while the bind pose has 0, so after a
 * mixer update `pose()` is how much of the clips shows: 1 is fully animated, 0 is the T-pose.
 */
function rig() {
  const root = new Object3D()
  const target = new Object3D()
  target.name = 'target'
  root.add(target)
  const mixer = new AnimationMixer(root)
  const clips = Object.values(CLIPS).map(
    (name) => new AnimationClip(name, 1, [new VectorKeyframeTrack('target.position', [0, 1], [1, 0, 0, 1, 0, 0])]),
  )
  const animator = new GaitAnimator((name) => {
    const clip = clips.find((c) => c.name === name)
    return clip && mixer.clipAction(clip)
  }, CLIPS)
  /**
   * One rendered frame, in PedestrianActor's order: drei's useFrame advances the mixer first,
   * then the actor picks the clip; the pose drawn is whatever the rig holds after both.
   */
  const frame = (gait: Gait) => {
    mixer.update(DT)
    animator.update(gait, 1)
    return target.position.x
  }
  return { mixer, animator, frame }
}

describe('GaitAnimator', () => {
  it('shows the first clip at full weight from the first frame', () => {
    const { frame } = rig()
    expect(frame('idle')).toBeCloseTo(1)
  })

  it('shows the first clip while playback is paused', () => {
    const { mixer, frame } = rig()
    mixer.timeScale = 0 // PedestrianActor freezes the mixer while the clock is paused
    for (let i = 0; i < 30; i++) expect(frame('walk')).toBeCloseTo(1)
  })

  it('restarts the clip after the mixer stopped every action', () => {
    const { mixer, frame } = rig()
    for (let i = 0; i < 30; i++) frame('walk')
    mixer.stopAllAction() // what drei's useAnimations cleanup does, e.g. on a hot reload
    mixer.update(DT)
    expect(frame('walk')).toBeCloseTo(1)
  })

  it('never shows the bind pose while crossfading, even when the gait flips quickly', () => {
    const { frame } = rig()
    const gaits: Gait[] = ['idle', 'walk', 'walk', 'run', 'walk', 'idle', 'walk', 'run', 'run', 'idle']
    for (const gait of gaits) {
      for (let i = 0; i < 6; i++) expect(frame(gait)).toBeGreaterThan(0.99) // 0.1 s, shorter than a fade
    }
  })

  it('reports the gait it shows', () => {
    const { animator, frame } = rig()
    expect(animator.gait).toBeUndefined()
    frame('run')
    expect(animator.gait).toBe('run')
  })
})
