import { Activity, BarChart3, BrainCircuit, Database, FlaskConical, ListChecks, Menu, Server, X } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { studioApi } from "../api";
import type { SystemHealth } from "../types";
import { PageErrorBoundary } from "./PageErrorBoundary";

export function AppShell() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    let active = true;
    const refresh = () => studioApi.health().then((value) => active && setHealth(value)).catch(() => active && setHealth(null));
    refresh();
    const timer = window.setInterval(refresh, 15000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <div className={location.pathname === "/live" ? "app-shell app-shell--live" : "app-shell"}>
      <header className="topbar">
        <div className="brand">
          <div className="brand__mark"><Activity size={21} /></div>
          <div>
            <strong>StateBus</strong>
            <span>Studio</span>
          </div>
        </div>

        <nav className={mobileOpen ? "main-nav is-open" : "main-nav"} aria-label="主导航">
          <NavLink to="/evidence" onClick={() => setMobileOpen(false)}>
            <BarChart3 size={18} />
            <span>实验与证据</span>
          </NavLink>
          <NavLink to="/live" onClick={() => setMobileOpen(false)}>
            <FlaskConical size={18} />
            <span>任务演示</span>
          </NavLink>
        </nav>

        <div className="topbar__right">
          <div className="topbar-health" aria-label="运行环境">
            <div className={health?.model_service.ok ? "topbar-health__item is-ready" : "topbar-health__item"} title={health?.model_service.url ?? "正在检查 vLLM"}>
              <Server size={14} /><span /><div><strong>vLLM</strong><small>{health?.model_service.ok ? "服务正常" : "离线"}</small></div>
            </div>
            <div className={health?.embedding_model.ok ? "topbar-health__item is-ready" : "topbar-health__item"} title={health?.embedding_model.runtime?.detail || "正在检查 Embedding runtime"}>
              <BrainCircuit size={14} /><span /><div><strong>Embedding</strong><small>{health?.embedding_model.ok ? (health.embedding_model.runtime.device.startsWith("cuda") ? "GPU 就绪" : "CPU 就绪") : "运行时异常"}</small></div>
            </div>
            <div className={health?.worker.ok && health?.role_worker?.ok ? "topbar-health__item is-ready" : "topbar-health__item"} title={health?.role_worker?.detail || "单 Worker 队列"}>
              <ListChecks size={14} /><span /><div><strong>任务队列</strong><small>{health?.worker.ok && health?.role_worker?.ok ? "单 Worker" : "环境异常"}</small></div>
            </div>
          </div>
          <button className="icon-button mobile-menu" onClick={() => setMobileOpen((value) => !value)} title="菜单">
            {mobileOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
      </header>
      <main className="app-main">
        <PageErrorBoundary resetKey={location.pathname}>
          <Outlet />
        </PageErrorBoundary>
      </main>
      {location.pathname !== "/live" && <footer className="app-footer">
        <span><Database size={14} />固定证据快照与实时运行记录分开存储</span>
        <span>StateBus</span>
      </footer>}
    </div>
  );
}
