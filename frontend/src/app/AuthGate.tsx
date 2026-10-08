import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, errorMessage, type Me, type Project, type StatusInfo } from "../api";
import { AppContext } from "./AppContext";
import { usePolling } from "../hooks/usePolling";
import { POLL } from "../lib/poll";

const DASHBOARD_LOGIN_URL = "/";

type GateState =
  | { kind: "loading" }
  | { kind: "ok"; me: Me }
  | { kind: "login" }
  | { kind: "error"; message: string };

/** 계약 §5.2: 401이면 "대시보드에서 로그인하세요" + 링크 */
export function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<GateState>({ kind: "loading" });
  const [projects, setProjects] = useState<Project[]>([]);
  const [status, setStatus] = useState<StatusInfo | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .me()
      .then((me) => alive && setState({ kind: "ok", me }))
      .catch((e) => {
        if (!alive) return;
        if (e instanceof ApiError && e.status === 401) setState({ kind: "login" });
        else setState({ kind: "error", message: errorMessage(e) });
      });
    return () => {
      alive = false;
    };
  }, []);

  const loggedIn = state.kind === "ok";
  useEffect(() => {
    if (!loggedIn) return;
    api.projects().then(setProjects).catch(() => setProjects([]));
  }, [loggedIn]);

  const loadStatus = useCallback(() => api.status().then(setStatus), []);
  usePolling(loadStatus, loggedIn ? POLL.status : null);

  if (state.kind === "loading") return <div className="gate">불러오는 중…</div>;
  if (state.kind === "login")
    return (
      <div className="gate">
        <h1>대시보드에서 로그인하세요</h1>
        <p>PhysicsAI는 해석 대시보드의 로그인을 그대로 사용합니다.</p>
        <a className="btn primary" href={DASHBOARD_LOGIN_URL}>
          대시보드로 이동
        </a>
      </div>
    );
  if (state.kind === "error")
    return (
      <div className="gate">
        <h1>접속할 수 없습니다</h1>
        <p>{state.message}</p>
      </div>
    );
  return <AppContext.Provider value={{ me: state.me, projects, status }}>{children}</AppContext.Provider>;
}
