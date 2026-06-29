import { Component, type ErrorInfo, type ReactNode } from "react";

interface State {
  error: Error | null;
}

/** Catches render-time crashes so a single bad stage can't blank the whole app. */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Studio render error:", error, info);
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <div className="empty" role="alert" style={{ marginTop: 40 }}>
          The studio hit an unexpected error. Reload the page to continue.
        </div>
      );
    }
    return this.props.children;
  }
}
