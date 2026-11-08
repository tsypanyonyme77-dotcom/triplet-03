export function ErrorNote({ error }: { error: string | null }) {
  return error ? <p className="error">{error}</p> : null
}
