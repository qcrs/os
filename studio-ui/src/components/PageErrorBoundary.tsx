import { Component, type ErrorInfo, type ReactNode } from "react";
import { RefreshCw, TriangleAlert } from "lucide-react";

interface PageErrorBoundaryProps {
  children: ReactNode;
  resetKey: string;
}

interface PageErrorBoundaryState {
  error: Error | null;
}

export class PageErrorBoundary extends Component<PageErrorBoundaryProps, PageErrorBoundaryState> {
  state: PageErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): PageErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("StateBus Studio page render failed", error, info);
  }

  componentDidUpdate(previousProps: PageErrorBoundaryProps) {
    if (previousProps.resetKey !== this.props.resetKey && this.state.error) {
      this.setState({ error: null });
    }
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <section className="page-error-boundary" role="alert">
        <span><TriangleAlert size={22} /></span>
        <div>
          <strong>运行视图暂时无法显示</strong>
          <p>实时记录包含了当前界面无法解析的数据。任务不会因此停止，重新载入后仍可从“完整记录”查看。</p>
          <code>{this.state.error.message}</code>
        </div>
        <button className="secondary-button" onClick={() => window.location.reload()}>
          <RefreshCw size={15} />重新载入
        </button>
      </section>
    );
  }
}
