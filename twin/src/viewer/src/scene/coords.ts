// Simulation space: x east, y north, heading = atan2(dy, dx) (0 = east, CCW).
// Three.js space: y up, ground on the XZ plane. Map sim (x, y) -> world (x, 0, -y),
// a proper rotation, so nothing is mirrored and north points to -Z.

/** Which way a model's nose points in its own file. */
export type ModelFacing = '+z' | '-z'

export function simToWorld(x: number, y: number): [number, number, number] {
  return [x, 0, -y]
}

/**
 * Yaw (rotation about +Y) that turns a model so it points along a sim heading.
 * World direction of a sim heading is (cos h, 0, -sin h). Rotating +Z by yaw gives
 * (sin yaw, 0, cos yaw), so yaw = h + pi/2 for a +Z-facing model; -Z models need pi more.
 */
export function headingToYaw(heading: number, facing: ModelFacing): number {
  return heading + Math.PI / 2 + (facing === '-z' ? Math.PI : 0)
}

/** Shortest signed angle from a to b, in (-pi, pi]. */
export function angleDelta(a: number, b: number): number {
  return Math.atan2(Math.sin(b - a), Math.cos(b - a))
}

/** Moves angle `current` toward `target` with time constant `tau` seconds (frame-rate independent). */
export function dampAngle(current: number, target: number, tau: number, dt: number): number {
  return current + angleDelta(current, target) * (1 - Math.exp(-dt / tau))
}
