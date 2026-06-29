export function ErrorBanner({ message, onDismiss }: { message: string; onDismiss: () => void }) {
  return (
    <div className="error-banner" role="alert">
      <span>
        <b>Something went wrong.</b> {message} The studio stays on the deterministic replay path —
        try again, or reload.
      </span>
      <button className="error-dismiss" aria-label="Dismiss error" onClick={onDismiss}>
        ✕
      </button>
    </div>
  );
}
