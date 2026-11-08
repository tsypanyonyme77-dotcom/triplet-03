/** Width of a painted bay line (m). */
export const LINE_M = 0.12

/**
 * One painted line of a bay, in the bay's own frame: origin at the bay centre,
 * +x along the direction of travel, +z toward the kerb (see ParkingBay).
 */
export interface BayLine {
  x: number
  z: number
  along: number // size along x
  across: number // size along z
}

/**
 * The markings of a parallel parking bay: a line along the edge of the driving lane
 * and one across each end, open on the kerb side. Every line stays inside the bay.
 */
export function bayLines(length: number, width: number): BayLine[] {
  const endX = length / 2 - LINE_M / 2
  return [
    { x: 0, z: -width / 2 + LINE_M / 2, along: length, across: LINE_M },
    { x: -endX, z: 0, along: LINE_M, across: width },
    { x: endX, z: 0, along: LINE_M, across: width },
  ]
}
