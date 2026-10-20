import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useApp, roleIn } from "../app/AppContext";
import { loginUrl } from "../app/AuthGate";
import { ROLE_LABEL } from "../lib/format";
import { NotificationBell } from "./NotificationBell";
import { VersionBadge } from "./VersionBadge";

export interface Crumb {
  label: string;
  to?: string;
}

export function PathBar({ crumbs }: { crumbs: Crumb[] }) {
  return (
    <nav className="pathbar R" aria-label="경로">
      {crumbs.map((c, i) => (
        <span key={i} className="crumb">
          {i > 0 && <span className="crumb-sep">›</span>}
          {c.to && i < crumbs.length - 1 ? <Link to={c.to}>{c.label}</Link> : <span aria-current={i === crumbs.length - 1 ? "page" : undefined}>{c.label}</span>}
        </span>
      ))}
    </nav>
  );
}

/** 상단 바: 브랜드 · 경로 · 버전 배지(→ 버전 게시판) · (Study 화면) 상태 칩 · 관리 · 대시보드로 · 알림 벨 · 사용자 */
export function TopBar({ crumbs, projectId, status: chips }: { crumbs: Crumb[]; projectId?: string; status?: ReactNode }) {
  const { me, status } = useApp();
  const role = roleIn(me, projectId);
  return (
    <header className="topbar">
      <Link to="/" className="brand T" aria-label="PhysicsAI 처음으로">
        <span className="brand-name">PhysicsAI</span>
      </Link>
      <PathBar crumbs={[{ label: "AI 예측", to: "/" }, ...crumbs]} />
      {status?.demo && (
        <span className="demo-badge R" data-testid="demo-badge" title="시연 모드: 가짜 데이터·도구로 동작합니다">
          시연 모드
        </span>
      )}
      <VersionBadge />
      <div className="topbar-right">
        {chips && <div className="status-chips">{chips}</div>}
        {me.is_global_admin && <AdminMenu />}
        <a className="topbar-link" href={status?.auth?.login_url || loginUrl()}>대시보드로</a>
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
  const warnings = status?.config.warnings?.length ?? 0;
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
        {(fail > 0 || warnings > 0) && (
          <span className="alert-dot" data-testid="admin-alert-dot" title={[fail ? `최근 환경 점검 실패 ${fail}건` : "", warnings ? `설정 경고 ${warnings}건` : ""].filter(Boolean).join(" · ")} />
        )}
      </button>
      {open && (
        <div className="admin-menu-pop" role="menu">
          <Link role="menuitem" to="/admin/env-check" onClick={() => setOpen(false)}>
            환경 점검
            {fail > 0 && <span className="muted small"> · 실패 {fail}</span>}
            {warnings > 0 && <span className="muted small"> · 설정 경고 {warnings}</span>}
          </Link>
        </div>
      )}
    </div>
  );
}
