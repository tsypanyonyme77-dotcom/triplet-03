import { useFrame } from '@react-three/fiber'
import { useEffect, useMemo, useRef } from 'react'
import { MeshStandardMaterial, type Group, type Object3D } from 'three'
import { usePlayback } from '../playback/ClockContext'
import { sampleEntity } from '../playback/sampleEntity'
import { headingToYaw, simToWorld } from '../scene/coords'
import { actorRegistry } from './actorRegistry'
import { fitCar } from './carFit'
import { LEGACY_VEHICLE_BODY, type CarModel } from './modelCatalog'
import { useClonedScene } from './useClonedScene'

const ROAD_WHEEL = /^wheel-(front|back)-(left|right)$/
const FRONT_WHEEL = /^wheel-front-/

// Body motion on its suspension, derived from the recorded acceleration (sim truth);
// a stiff family car: about 0.5 degrees per m/s^2, a few degrees at most.
const WHEELBASE_M = 2.7 // simulation/app/vehicle_dynamics.py VehicleSpec
const PITCH_PER_MS2 = (0.5 * Math.PI) / 180
const ROLL_PER_MS2 = (0.7 * Math.PI) / 180
const MAX_TILT = (4 * Math.PI) / 180
const BRAKE_LIGHT_ON_MS2 = -0.4 // decelerating harder than engine braking, or standing still
// brake lamps, in model units (tuned on the Kenney cars: 0.75 m high and 0.6 m off centre at x1.6)
const LAMP_HEIGHT = 0.47
const LAMP_OFFSET = 0.375
const clamp = (v: number, m: number) => Math.min(Math.max(v, -m), m)

export function CarActor({ id, model }: { id: string; model: CarModel }) {
  const { clock, recording } = usePlayback()
  const { scene } = useClonedScene(model.url)
  const group = useRef<Group>(null)
  const body = useRef<Group>(null)
  const vehicle = recording.map.vehicle ?? LEGACY_VEHICLE_BODY
  const fit = useMemo(() => fitCar(model, vehicle), [model, vehicle])
  // one material per car, shared by both lamps
  const brake = useMemo(() => new MeshStandardMaterial({ color: '#5a0000', emissive: '#ff1a1a', emissiveIntensity: 0.15 }), [])
  const wheels = useMemo(() => {
    const found: { node: Object3D; front: boolean }[] = []
    scene.traverse((o) => {
      if (ROAD_WHEEL.test(o.name)) {
        o.rotation.order = 'YXZ' // steer about the vertical first, then spin about the steered axle
        found.push({ node: o, front: FRONT_WHEEL.test(o.name) }) // not the SUV's spare "wheel-back"
      }
    })
    return found
  }, [scene])

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
    const s = sampleEntity(recording.frames, recording.dt, clock.time, id, (f) => f.cars)
    g.visible = s !== undefined
    if (!s) return
    g.position.set(...simToWorld(s.x, s.y))
    g.rotation.y = headingToYaw(s.heading, model.facing)

    // nose dips under braking, squats when accelerating; leans out of turns
    const lateral = (s.speed * s.speed * Math.tan(s.steer)) / WHEELBASE_M // + = turning left
    if (body.current) {
      body.current.rotation.x = clamp(-s.accel * PITCH_PER_MS2, MAX_TILT)
      body.current.rotation.z = clamp(lateral * ROLL_PER_MS2, MAX_TILT)
    }

    const spin = clock.paused ? 0 : (s.speed / (model.wheelRadius * fit.scale)) * delta * clock.rate
    for (const w of wheels) {
      w.node.rotation.x += spin
      w.node.rotation.y = w.front ? s.steer : 0
    }
    const braking = s.accel < BRAKE_LIGHT_ON_MS2 || s.speed < 0.1 || s.status === 'crashed'
    brake.emissiveIntensity = braking ? 2.5 : 0.15
  })

  return (
    <group ref={group}>
      {/* sim position is the front bumper: the body is drawn behind it, tilting about its middle,
          and the model is fitted inside it (carFit.ts) */}
      <group ref={body} position-z={-vehicle.length / 2}>
        <primitive object={scene} scale={fit.scale} position-z={fit.offsetZ} />
        {[-1, 1].map((side) => (
          <mesh key={side} position={[side * LAMP_OFFSET * fit.scale, LAMP_HEIGHT * fit.scale, -fit.length / 2 - 0.02]} material={brake}>
            <boxGeometry args={[0.35, 0.12, 0.05]} />
          </mesh>
        ))}
      </group>
    </group>
  )
}
