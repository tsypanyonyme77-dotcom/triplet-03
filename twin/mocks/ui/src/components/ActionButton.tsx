import { useState } from 'react'

/** A button that runs one call, stays disabled meanwhile, and shows what came back. */
export function ActionButton({ label, run }: { label: string; run: () => Promise<string> }) {
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState<{ text: string; failed: boolean } | null>(null)
  const click = () => {
    setBusy(true)
    run()
      .then((text) => setNote({ text, failed: false }))
      .catch((e: unknown) => setNote({ text: String(e), failed: true }))
      .finally(() => setBusy(false))
  }

  return (
    <span className="action">
      <button type="button" disabled={busy} onClick={click}>
        {label}
      </button>
      {note && <small className={note.failed ? 'error' : 'note'}>{note.text}</small>}
    </span>
  )
}
