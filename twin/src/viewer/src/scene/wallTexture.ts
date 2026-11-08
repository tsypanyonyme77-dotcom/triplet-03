import { renderToStaticMarkup } from 'react-dom/server'
import { createElement } from 'react'
import { CanvasTexture, SRGBColorSpace } from 'three'
import { categoryIcon } from '../icons/civilianIcons'
import { type PlaceRole, colorOf } from './placeLabels'

const W = 512
const H = 128

const THEME: Record<PlaceRole, { background: string; ink: string }> = {
  plain: { background: 'rgba(255,255,255,0.94)', ink: '#1f2540' },
  destination: { background: '#1f2540', ink: '#ffffff' },
  home: { background: '#fef3c7', ink: '#1f2540' },
  duty: { background: '#fef3c7', ink: '#1f2540' },
}

/** The category icon as an image, drawn from the same lucide icon the panels use. */
function iconImage(category: string, color: string): HTMLImageElement {
  const svg = renderToStaticMarkup(createElement(categoryIcon(category), { size: 96, color, strokeWidth: 2.2 }))
  const img = new Image()
  img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
  return img
}

/**
 * The sign painted on a building's walls: its kind's icon and its name on a rounded plate.
 * The text is drawn at once; the icon joins as soon as its image has loaded.
 */
export function makeWallTexture(name: string, category: string, role: PlaceRole): CanvasTexture {
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')!
  const texture = new CanvasTexture(canvas)
  texture.colorSpace = SRGBColorSpace
  texture.anisotropy = 8
  const { background, ink } = THEME[role]
  const accent = role === 'destination' ? '#ffffff' : colorOf(category)

  const paint = (icon: HTMLImageElement | null) => {
    ctx.clearRect(0, 0, W, H)
    ctx.fillStyle = background
    ctx.beginPath()
    ctx.roundRect(4, 4, W - 8, H - 8, 28)
    ctx.fill()
    ctx.lineWidth = 8
    ctx.strokeStyle = colorOf(category)
    ctx.stroke()
    if (icon) ctx.drawImage(icon, 24, 16, 96, 96)
    let size = 64
    ctx.font = `800 ${size}px ui-rounded, Nunito, "Segoe UI", system-ui, sans-serif`
    const room = W - 150 - 24
    while (ctx.measureText(name).width > room && size > 24) {
      size -= 4
      ctx.font = `800 ${size}px ui-rounded, Nunito, "Segoe UI", system-ui, sans-serif`
    }
    ctx.fillStyle = ink
    ctx.textBaseline = 'middle'
    ctx.fillText(name, 136, H / 2 + 3)
    texture.needsUpdate = true
  }

  paint(null)
  const icon = iconImage(category, accent)
  icon.onload = () => paint(icon)
  return texture
}
