import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useApp, roleIn } from "../app/AppContext";
import { ROLE_LABEL } from "../lib/format";
import { NotificationBell } from "./NotificationBell";

export interface Crumb {
  label: string;
  to?: string;
}

export function PathBar({ crumbs }: { crumbs: Crumb[] }) {
  return (
    <nav className="pathbar" aria-label="경로">
      {crumbs.map((c, i) => (
        <span key={i} className="crumb">
          {i > 0 && <span className="crumb-sep">›</span>}
          {c.to && i < crumbs.length - 1 ? <Link to={c.to}>{c.label}</Link> : <span aria-current={i === crumbs.length - 1 ? "page" : undefined}>{c.label}</span>}
        </span>
      ))}
    </nav>
  );
}

export function TopBar({ crumbs, projectId }: { crumbs: Crumb[]; projectId?: string }) {
  const { me } = useApp();
  const role = roleIn(me, projectId);
  return (
    <header className="topbar">
      <Link to="/" className="brand" aria-label="PhysicsAI 처음으로">
        <span className="brand-mark">Φ</span>
        <span className="brand-name">PhysicsAI</span>
      </Link>
      <PathBar crumbs={[{ label: "AI 예측", to: "/" }, ...crumbs]} />
      <div className="topbar-right">
        {me.is_global_admin && <AdminMenu />}
        <a className="topbar-link" href="/">대시보드로</a>
        <NotificationBell />
        <span className="user" title={me.username}>
          <span className="user-name">{me.display_name}</span>
          {me.is_global_admin ? (
            <span className="role-chip admin">전역 관리자</span>
          ) : role ? (
            <span className={`role-chip ${role}`}>{ROLE_LABEL[role]}</span>
          ) : projectId ? (
            <span className="role-chip general">비멤버</span>
          ) : null}
        </span>
      </div>
    </header>
  );
}

/** phase2.md §14.1: 전역 관리자에게만 "관리 > 환경 점검", 최근 점검 실패가 있으면 빨간 점 */
function AdminMenu() {
  const { status } = useApp();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const fail = status?.env_check?.fail ?? 0;
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  return (
    <div className="admin-menu" ref={ref}>
      <button type="button" className="topbar-link admin-menu-btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        관리
        {fail > 0 && <span className="alert-dot" data-testid="admin-alert-dot" title={`최근 환경 점검 실패 ${fail}건`} />}
      </button>
      {open && (
        <div className="admin-menu-pop" role="menu">
          <Link role="menuitem" to="/admin/env-check" onClick={() => setOpen(false)}>
            환경 점검
            {fail > 0 && <span className="muted small"> · 실패 {fail}</span>}
          </Link>
        </div>
      )}
    </div>
  );
}
