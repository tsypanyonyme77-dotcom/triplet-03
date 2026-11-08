import type { Object3D } from 'three'

/** Live actor objects by id, so the camera can follow one without React re-renders. */
export const actorRegistry = new Map<string, Object3D>()
