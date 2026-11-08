import { Check, Flame, MapPinCheck, Siren, TriangleAlert, X, type LucideIcon } from 'lucide-react'
import type { EventIcon, HudEvent } from './events'

const ICONS: Record<EventIcon, LucideIcon> = {
  fire: Flame,
  accident: TriangleAlert,
  siren: Siren,
  arrived: MapPinCheck,
  check: Check,
}

/** Top centre: short notices for what just happened. They leave by themselves. */
export function ToastStack({ toasts, onDismiss }: { toasts: HudEvent[]; onDismiss: (key: string) => void }) {
  if (toasts.length === 0) return null
  return (
    <div className="toast-stack" role="alert" aria-live="polite">
      {toasts.map((t) => {
        const Icon = ICONS[t.icon]
        return (
          <div key={t.key} className={`hud-card toast-card ${t.tone}`}>
            <Icon size={20} />
            <span>
              <strong>{t.title}</strong>
              <span>{t.text}</span>
            </span>
            <button type="button" aria-label="Dismiss" onClick={() => onDismiss(t.key)}>
              <X size={14} />
            </button>
          </div>
        )
      })}
    </div>
  )
}
