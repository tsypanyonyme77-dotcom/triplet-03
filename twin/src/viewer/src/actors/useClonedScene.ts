import { useGLTF } from '@react-three/drei'
import { useMemo } from 'react'
import { Color, type AnimationClip, type Material, type Mesh, type MeshStandardMaterial, type Object3D } from 'three'
import { clone as cloneSkinned } from 'three/addons/utils/SkeletonUtils.js'

/** Something to recolour in one actor's copy: the material with this name gets this colour. */
export interface Recolour {
  material: string
  color: string
}

/**
 * Loads a .glb once (cached by drei) and returns a private copy of its scene for
 * one actor. SkeletonUtils.clone keeps skinned meshes bound to their own skeleton,
 * which a plain Object3D.clone does not. A recoloured material is copied first, so
 * the other actors sharing the file keep theirs.
 */
export function useClonedScene(url: string, recolour?: Recolour): { scene: Object3D; animations: AnimationClip[] } {
  const gltf = useGLTF(url)
  const scene = useMemo(() => {
    const copy = cloneSkinned(gltf.scene)
    copy.traverse((o) => {
      o.castShadow = true
      o.receiveShadow = true
      const mesh = o as Mesh
      if (!recolour || !mesh.isMesh) return
      const swap = (m: Material) => {
        if (m.name !== recolour.material) return m
        const own = m.clone() as MeshStandardMaterial
        own.color = new Color(recolour.color)
        return own
      }
      mesh.material = Array.isArray(mesh.material) ? mesh.material.map(swap) : swap(mesh.material)
    })
    return copy
  }, [gltf.scene, recolour?.material, recolour?.color])
  return { scene, animations: gltf.animations }
}
