import { CanvasTexture, RepeatWrapping, SRGBColorSpace, type Texture } from 'three'
import type { BuildingLook } from './buildingStyle'

// Facades are drawn once per look on a canvas, as a tile of 2 bays by 2 floors, and repeated over the
// walls. Each wall gets its own copy of the texture (sharing the image) with its own repeat.

const PX_PER_TILE = 256
const GLASS = ['#26405a', '#2d4a66', '#1f3346']
const LIT = '#f3d27a'
const cache = new Map<string, CanvasTexture>()

function canvas(): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const c = document.createElement('canvas')
  c.width = c.height = PX_PER_TILE
  const ctx = c.getContext('2d')
  if (!ctx) throw new Error('2D canvas not available')
  return [c, ctx]
}

function wall(ctx: CanvasRenderingContext2D, look: BuildingLook) {
  ctx.fillStyle = look.wall
  ctx.fillRect(0, 0, PX_PER_TILE, PX_PER_TILE)
  if (!look.brick) {
    // plaster: a faint mottle
    for (let i = 0; i < 400; i++) {
      ctx.fillStyle = `rgba(0,0,0,${0.02 + ((i * 37) % 5) / 200})`
      ctx.fillRect((i * 53) % PX_PER_TILE, (i * 97) % PX_PER_TILE, 3, 3)
    }
    return
  }
  // brick courses with offset joints
  ctx.strokeStyle = 'rgba(255,240,225,0.35)'
  ctx.lineWidth = 1
  const course = 8
  for (let y = 0; y < PX_PER_TILE; y += course) {
    ctx.beginPath()
    ctx.moveTo(0, y)
    ctx.lineTo(PX_PER_TILE, y)
    ctx.stroke()
    for (let x = (y / course) % 2 ? 0 : 12; x < PX_PER_TILE; x += 24) {
      ctx.beginPath()
      ctx.moveTo(x, y)
      ctx.lineTo(x, y + course)
      ctx.stroke()
    }
  }
}

function texture(key: string, draw: (ctx: CanvasRenderingContext2D) => void): CanvasTexture {
  const hit = cache.get(key)
  if (hit) return hit
  const [c, ctx] = canvas()
  draw(ctx)
  const t = new CanvasTexture(c)
  t.wrapS = t.wrapT = RepeatWrapping
  t.colorSpace = SRGBColorSpace
  t.anisotropy = 4
  cache.set(key, t)
  return t
}

/** Upper floors: windows with frames and sills, a few lit. */
export function windowsTexture(look: BuildingLook): CanvasTexture {
  return texture(`win|${look.textureKey}`, (ctx) => {
    wall(ctx, look)
    const cell = PX_PER_TILE / 2
    const w = cell * look.windowW
    const h = cell * look.windowH
    for (let row = 0; row < 2; row++) {
      for (let col = 0; col < 2; col++) {
        const x = col * cell + (cell - w) / 2
        const y = row * cell + (cell - h) / 2
        ctx.fillStyle = look.trim
        ctx.fillRect(x - 4, y - 4, w + 8, h + 8)
        ctx.fillStyle = (row * 2 + col) % 4 === 1 ? LIT : GLASS[(row + col) % GLASS.length]
        ctx.fillRect(x, y, w, h)
        // a glint, and the mullion
        ctx.fillStyle = 'rgba(255,255,255,0.18)'
        ctx.fillRect(x + 3, y + 3, w * 0.25, h - 6)
        ctx.fillStyle = look.trim
        ctx.fillRect(x + w / 2 - 1.5, y, 3, h)
        ctx.fillRect(x - 6, y + h + 4, w + 12, 5) // sill
      }
    }
  })
}

/** Ground floor: a shop front (glass, a door, a fascia) or plain windows for a building without a shop. */
export function groundTexture(look: BuildingLook): CanvasTexture {
  return texture(`gnd|${look.shop}|${look.textureKey}`, (ctx) => {
    wall(ctx, look)
    const cell = PX_PER_TILE / 2
    if (!look.shop) {
      for (let col = 0; col < 2; col++) {
        const x = col * cell + cell * 0.25
        ctx.fillStyle = look.trim
        ctx.fillRect(x - 4, PX_PER_TILE * 0.35 - 4, cell * 0.5 + 8, PX_PER_TILE * 0.35 + 8)
        ctx.fillStyle = GLASS[col]
        ctx.fillRect(x, PX_PER_TILE * 0.35, cell * 0.5, PX_PER_TILE * 0.35)
      }
      return
    }
    // fascia band at the top, then shop glass with a door in each bay
    ctx.fillStyle = look.trim
    ctx.fillRect(0, 0, PX_PER_TILE, PX_PER_TILE * 0.16)
    for (let col = 0; col < 2; col++) {
      const x0 = col * cell + 8
      ctx.fillStyle = look.trim
      ctx.fillRect(x0 - 4, PX_PER_TILE * 0.22, cell - 8, PX_PER_TILE * 0.78)
      ctx.fillStyle = '#7fa6bf'
      ctx.fillRect(x0, PX_PER_TILE * 0.26, cell - 16, PX_PER_TILE * 0.74)
      ctx.fillStyle = 'rgba(255,255,255,0.2)'
      ctx.fillRect(x0 + 4, PX_PER_TILE * 0.28, (cell - 16) * 0.2, PX_PER_TILE * 0.68)
      ctx.fillStyle = '#3a2e26' // the door
      ctx.fillRect(x0 + (cell - 16) * 0.62, PX_PER_TILE * 0.36, (cell - 16) * 0.28, PX_PER_TILE * 0.64)
    }
  })
}

/** A copy of `base` (same image) repeated `u` times across and `v` times up. */
export function repeated(base: Texture, u: number, v: number): Texture {
  const t = base.clone()
  t.repeat.set(Math.max(u, 0.01), Math.max(v, 0.01))
  t.needsUpdate = true
  return t
}
