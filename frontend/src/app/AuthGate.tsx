import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, AUTH_LOST_EVENT, errorMessage, type Me, type Project, type StatusInfo } from "../api";
import { AppContext } from "./AppContext";
import { usePolling } from "../hooks/usePolling";
import { POLL, applyUiPoll } from "../lib/poll";

const LOGIN_URL_KEY = "physicsai.loginUrl";

/** 로그인 링크: /status.auth.login_url(B1)을 기억해 두고, 모르면 "/" */
function loginUrl(): string {
  try {
    return localStorage.getItem(LOGIN_URL_KEY) || "/";
  } catch {
    return "/";
  }
}

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

  useEffect(() => {
    const onLost = () => setState({ kind: "login" });
    window.addEventListener(AUTH_LOST_EVENT, onLost);
    return () => window.removeEventListener(AUTH_LOST_EVENT, onLost);
  }, []);

  const loggedIn = state.kind === "ok";
  useEffect(() => {
    if (!loggedIn) return;
    api.projects().then(setProjects).catch(() => setProjects([]));
  }, [loggedIn]);

  const loadStatus = useCallback(
    () =>
      api.status().then((st) => {
        applyUiPoll(st.ui);
        if (st.auth?.login_url) {
          try {
            localStorage.setItem(LOGIN_URL_KEY, st.auth.login_url);
          } catch {
            /* 무시 */
          }
        }
        setStatus(st);
      }),
    [],
  );
  usePolling(loadStatus, loggedIn ? POLL.status : null);

  if (state.kind === "loading") return <div className="gate">불러오는 중…</div>;
  if (state.kind === "login")
    return (
      <div className="gate">
        <h1>대시보드에서 로그인하세요</h1>
        <p>PhysicsAI는 해석 대시보드의 로그인을 그대로 사용합니다.</p>
        <a className="btn primary" href={loginUrl()}>
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
