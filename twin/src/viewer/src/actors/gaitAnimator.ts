import type { AnimationAction } from 'three'
import type { Gait } from './locomotion'

const CROSSFADE_S = 0.25

/** Finds the mixer action of a clip by name; undefined while the actor has no root yet. */
export type ActionLookup = (clipName: string) => AnimationAction | undefined

/**
 * Plays one actor's idle / walk / run clip on its AnimationMixer and crossfades
 * between them when the gait changes.
 */
export class GaitAnimator {
  private readonly actionFor: ActionLookup
  private readonly clips: Record<Gait, string>
  private current: { gait: Gait; action: AnimationAction } | null = null

  constructor(actionFor: ActionLookup, clips: Record<Gait, string>) {
    this.actionFor = actionFor
    this.clips = clips
  }

  /** The gait being shown, undefined before the first update. */
  get gait(): Gait | undefined {
    return this.current?.gait
  }

  /** Call once per frame with the gait to show and its clip playback rate. */
  update(gait: Gait, timeScale: number): void {
    if (!this.current?.action.isRunning()) {
      // Nothing is playing: the first frame, or the mixer stopped every action (drei's
      // useAnimations cleanup does, e.g. on a hot reload). A fade-in starts at weight 0 and
      // would show the model's bind pose (T-pose), for good if the mixer is frozen by a pause.
      const action = this.actionFor(this.clips[gait])
      if (action) {
        action.reset().setEffectiveWeight(1).play()
        // the mixer already ran this frame (drei's useFrame comes first): pose the rig now,
        // or this frame is still drawn in the bind pose
        action.getMixer().update(0)
        this.current = { gait, action }
      }
    } else if (this.current.gait !== gait) {
      const next = this.actionFor(this.clips[gait])
      if (next) {
        // a clip still fading out keeps its phase: restarting it from frame 0 makes the feet jump
        if (!next.isRunning()) next.reset()
        next.fadeIn(CROSSFADE_S).play()
        this.current.action.fadeOut(CROSSFADE_S)
        this.current = { gait, action: next }
      }
    }
    if (this.current) this.current.action.timeScale = timeScale
  }
}
