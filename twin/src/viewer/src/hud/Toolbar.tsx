import type { LucideIcon } from 'lucide-react'

export interface Tool {
  id: string
  label: string
  icon: LucideIcon
}

/** The left edge: one round button per drawer. Pressing the open one closes it. */
export function Toolbar({ tools, open, onToggle }: { tools: Tool[]; open: string | null; onToggle: (id: string) => void }) {
  return (
    <nav className="hud-card toolbar" aria-label="Tools">
      {tools.map(({ id, label, icon: Icon }) => (
        <button key={id} type="button" className={`round tool${open === id ? ' on' : ''}`} title={label} aria-pressed={open === id} onClick={() => onToggle(id)}>
          <Icon size={20} />
          <span className="tool-label">{label}</span>
        </button>
      ))}
    </nav>
  )
}
