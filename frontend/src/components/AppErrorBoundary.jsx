import React from "react";

class AppErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      hasError: false,
      message: "",
    };
  }

  static getDerivedStateFromError(error) {
    return {
      hasError: true,
      message: String(error?.message ?? error ?? "Unknown frontend error"),
    };
  }

  componentDidCatch(error, errorInfo) {
    // Keep full stack in devtools for root-cause investigation.
    // eslint-disable-next-line no-console
    console.error("AppErrorBoundary caught error:", error, errorInfo);
  }

  render() {
    if (!this.state.hasError) {
      return this.props.children;
    }

    return (
      <div className="app-error-boundary" role="alert">
        <h2>Frontend Error</h2>
        <p>{this.state.message || "The page crashed unexpectedly."}</p>
        <button
          className="action-btn"
          type="button"
          onClick={() => {
            window.location.reload();
          }}
        >
          Reload Page
        </button>
      </div>
    );
  }
}

export default AppErrorBoundary;
