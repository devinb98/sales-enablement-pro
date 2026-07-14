export default function Spinner({ label = 'Loading…' }) {
  return (
    <div className="spinner" role="status" aria-live="polite">
      <div className="spinner__ring" aria-hidden="true" />
      <span>{label}</span>
    </div>
  )
}
