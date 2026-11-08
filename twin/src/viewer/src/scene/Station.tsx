import { Html } from '@react-three/drei'
import type { StationData, StationKind } from '../recording/types'

const WIDTH_M = 14 // along the street
const DEPTH_M = 12 // away from the street
const HEIGHT_M = 7

const STYLE: Record<StationKind, { wall: string; band: string; bay: string }> = {
  hospital: { wall: '#eef1f2', band: '#d62828', bay: '#e8e8e8' },
  police_station: { wall: '#c9d3e3', band: '#1f3c88', bay: '#3d5bb8' },
  fire_station: { wall: '#e4d2c6', band: '#b3201a', bay: '#d23a2a' },
}

/**
 * A station building on the building line behind the sidewalk (data.front, facing the street),
 * a coloured band over its door, a label, and its vehicles' bays painted in the station colour.
 * Local frame of the building group: +x along the street, +z away from it.
 */
export function Station({ data }: { data: StationData }) {
  const style = STYLE[data.kind]
  // facing points from the building to the street; the group's +x runs along the street
  const along = data.facing - Math.PI / 2
  return (
    <group>
      <group position={[data.front[0], 0, -data.front[1]]} rotation-y={along}>
        <mesh position={[0, HEIGHT_M / 2, DEPTH_M / 2]} castShadow receiveShadow>
          <boxGeometry args={[WIDTH_M, HEIGHT_M, DEPTH_M]} />
          <meshStandardMaterial color={style.wall} />
        </mesh>
        <mesh position={[0, HEIGHT_M - 1.2, -0.05]}>
          <boxGeometry args={[WIDTH_M, 1.2, 0.1]} />
          <meshStandardMaterial color={style.band} />
        </mesh>
        {data.kind === 'hospital' && <RedCross />}
        <Html position={[0, HEIGHT_M + 1.5, DEPTH_M / 2]} center>
          <div className="station-label" style={{ background: style.band }}>
            {data.label}
          </div>
        </Html>
      </group>
      {data.bays.map((b) => (
        <mesh key={b.spot_id} position={[b.x, 0.02, -b.y]} rotation-y={b.heading} receiveShadow>
          <boxGeometry args={[5.5, 0.01, 2.6]} />
          <meshStandardMaterial color={style.bay} transparent opacity={0.55} />
        </mesh>
      ))}
    </group>
  )
}

function RedCross() {
  return (
    <group position={[0, HEIGHT_M / 2, -0.06]}>
      <mesh>
        <boxGeometry args={[2.4, 0.8, 0.05]} />
        <meshStandardMaterial color="#d62828" />
      </mesh>
      <mesh>
        <boxGeometry args={[0.8, 2.4, 0.05]} />
        <meshStandardMaterial color="#d62828" />
      </mesh>
    </group>
  )
}
