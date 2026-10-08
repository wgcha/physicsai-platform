import { useCallback, useEffect, useState } from "react";
import { api, errorMessage, type EnvCategory, type EnvCheck, type EnvCheckSummary, type EnvItemStatus } from "../api";
import { useApp } from "../app/AppContext";
import { TopBar } from "../shell/TopBar";
import { usePolling } from "../hooks/usePolling";
import { CodeLine } from "../components/ui";
import { JsonTree } from "../components/JsonTree";
import { fmtTime } from "../lib/format";

const CATEGORY_LABEL: Record<EnvCategory, string> = {
  CONFIG: "설정",
  DATABASE: "데이터베이스",
  AUTH: "인증",
  HPC: "PBS",
  WORKER: "워커",
  EXECUTABLE: "실행 파일",
  RESOURCE: "원본 자원",
  STORAGE: "저장소",
  GPU: "GPU",
};
const STATUS_LABEL: Record<EnvItemStatus, string> = { OK: "정상", WARN: "경고", FAIL: "실패", SKIP: "건너뜀", PENDING: "대기" };
const STATE_LABEL: Record<EnvCheck["state"], string> = { PENDING: "대기", RUNNING: "점검 중", DONE: "완료", FAILED: "실패", EXPIRED: "만료" };
const ENV_POLL_MS = { value: 2000 };
/** 시험에서 짧게 */
export function setEnvPollMs(ms: number) {
  ENV_POLL_MS.value = ms;
}

export function summaryText(s: EnvCheckSummary["summary"]): string {
  return `실패 ${s.fail} · 경고 ${s.warn} · 정상 ${s.ok} · 건너뜀 ${s.skip}`;
}

/** phase2.md §14.6 환경 점검(전역 관리자 전용) */
export function AdminEnvCheck() {
  const { me } = useApp();
  return (
    <div className="page">
      <TopBar crumbs={[{ label: "관리" }, { label: "환경 점검" }]} />
      <main className="page-main env-page">{me.is_global_admin ? <EnvCheckBody /> : <div className="empty" role="alert">관리자 전용입니다</div>}</main>
    </div>
  );
}

/** /status.config.warnings: 기동은 막지 않는 설정 안내(누락 → 기능 비활성, 예약 키) */
function ConfigWarnings() {
  const { status } = useApp();
  const w = status?.config.warnings ?? [];
  if (!w.length) return null;
  return (
    <section className="card wide config-warnings" aria-label="설정 경고">
      <div className="card-body">
        <div className="warn-text">
          <b>설정 경고 {w.length}건</b> <span className="muted small">— 기동은 되지만 해당 기능이 비활성입니다</span>
        </div>
        <ul className="mono small warn-list">
          {w.map((x) => (
            <li key={x}>{x}</li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function EnvCheckBody() {
  const [history, setHistory] = useState<EnvCheckSummary[]>([]);
  const [current, setCurrent] = useState<EnvCheck | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const loadHistory = useCallback(async () => {
    try {
      const { items } = await api.envChecks(20);
      setHistory(items);
      setSelectedId((cur) => cur ?? items[0]?.id ?? null);
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);
  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  const loadCurrent = useCallback(async () => {
    if (!selectedId) return;
    const c = await api.envCheck(selectedId);
    setCurrent(c);
    if (c.state !== "PENDING" && c.state !== "RUNNING") void loadHistory();
  }, [selectedId, loadHistory]);
  useEffect(() => {
    setCurrent(null);
    void loadCurrent().catch((e) => setError(errorMessage(e)));
  }, [loadCurrent]);

  const active = current?.state === "PENDING" || current?.state === "RUNNING";
  const busy = starting || active || history.some((h) => h.state === "PENDING" || h.state === "RUNNING");
  usePolling(loadCurrent, active ? ENV_POLL_MS.value : null, false, [selectedId]);

  const start = async () => {
    setStarting(true);
    setError(null);
    try {
      const c = await api.runEnvCheck();
      setCurrent(c);
      setSelectedId(c.id);
      await loadHistory();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setStarting(false);
    }
  };

  const groups = new Map<EnvCategory, EnvCheck["items"]>();
  for (const it of current?.items ?? []) groups.set(it.category, [...(groups.get(it.category) ?? []), it]);

  return (
    <div className="env-grid">
      <ConfigWarnings />
      <section className="card wide" aria-label="환경 점검">
        <header className="card-head">
          <h3>환경 점검</h3>
          <button type="button" className="btn primary" onClick={() => void start()} disabled={busy}>
            {busy ? "점검 중…" : "점검 실행"}
          </button>
        </header>
        <div className="card-body">
          {error && <div className="error-text small">{error}</div>}
          {!current ? (
            <p className="muted">{history.length ? "불러오는 중…" : "점검 이력이 없습니다. \"점검 실행\"을 누르세요."}</p>
          ) : (
            <>
              <div className="env-summary" data-testid="env-summary">
                <b>{summaryText(current.summary)}</b>
                <span className="muted small">
                  {STATE_LABEL[current.state]} · {current.requested_by_name} · {fmtTime(current.created_at)}
                  {current.worker_id ? ` · ${current.worker_id}` : ""}
                </span>
              </div>
              {current.failure_message && <div className="error-text small">{current.failure_message}</div>}
              {current.state === "EXPIRED" && <div className="warn-text small">워커가 시간 안에 점검하지 못해 만료되었습니다(워커 항목 미수행).</div>}
              {current.report_display_path && <CodeLine text={current.report_display_path} />}
              <div className="table-wrap">
                <table className="table compact env-table" aria-label="점검 결과">
                  <thead>
                    <tr>
                      <th>범주</th>
                      <th>항목</th>
                      <th>결과</th>
                      <th>메시지</th>
                      <th>세부</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[...groups.entries()].map(([cat, items]) =>
                      items.map((it, i) => (
                        <tr key={it.key} className={`env-${it.status.toLowerCase()}`}>
                          {i === 0 && (
                            <td rowSpan={items.length} className="env-cat">
                              {CATEGORY_LABEL[cat] ?? cat}
                            </td>
                          )}
                          <td>
                            {it.label}
                            <div className="mono muted small">{it.key}</div>
                          </td>
                          <td className="nowrap">
                            <span className={`env-dot ${it.status.toLowerCase()}`} aria-hidden="true" /> {STATUS_LABEL[it.status]}
                          </td>
                          <td className="small">{it.message}</td>
                          <td>
                            {it.detail ? (
                              <details>
                                <summary className="small">보기</summary>
                                <JsonTree data={it.detail} />
                              </details>
                            ) : null}
                          </td>
                        </tr>
                      )),
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </section>
      <section className="card" aria-label="최근 이력">
        <header className="card-head">
          <h3>최근 이력</h3>
        </header>
        <div className="card-body">
          <table className="table compact" aria-label="점검 이력">
            <thead>
              <tr>
                <th>시각</th>
                <th>요청자</th>
                <th>상태</th>
                <th>요약</th>
              </tr>
            </thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.id} className={`clickable ${h.id === selectedId ? "selected" : ""}`} onClick={() => setSelectedId(h.id)}>
                  <td className="small">
                    <button type="button" className="link small" onClick={() => setSelectedId(h.id)}>
                      {fmtTime(h.created_at)}
                    </button>
                  </td>
                  <td className="small">{h.requested_by_name}</td>
                  <td className="small">{STATE_LABEL[h.state]}</td>
                  <td className="small">{summaryText(h.summary)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
