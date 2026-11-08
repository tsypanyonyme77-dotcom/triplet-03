import { X } from 'lucide-react'
import type { ReactNode } from 'react'

/** A card that opens beside the toolbar. */
export function Drawer({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <section className="hud-card drawer" aria-label={title}>
      <header>
        <h2>{title}</h2>
        <button type="button" className="round ghost small" aria-label="Close" onClick={onClose}>
          <X size={16} />
        </button>
      </header>
      {children}
    </section>
  )
}
