// ④ "일괄 예측(DOE)" 모드(D3-53): 서브 탭 "실행 목록" | "새 일괄 예측".
// 실행 목록 = GET /studies/{id}/predict-batches — 진행 중·완료·실패·취소 전부(최신순): 번호·템플릿·조합 수·상태 집계·
// 응답 요약(첫 응답 최소~최대)·시작 시각. 아무 행 → 그 배치 결과 화면 …/stage/4/batch/:id.
// 기본 탭: 실행 중·대기 배치가 있으면 실행 목록, 없으면 마지막 선택(없으면 새 일괄 예측). 선택은 브라우저별 기억(try/catch).
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, errorMessage, type PredictBatchSummary } from "../../../api";
import { useStudy } from "../../../app/StudyContext";
import { Card } from "../../../components/ui";
import { usePolling } from "../../../hooks/usePolling";
import { fmtNum, fmtTime } from "../../../lib/format";
import { POLL } from "../../../lib/poll";
import { BatchSetup } from "./BatchSetup";
import { BATCH_STATUS_LABEL, batchTone, isBatchActive } from "./batchTable";

export type BatchTab = "list" | "new";
export const BATCH_TAB_KEY = "physicsai.stage4.batchTab";
const TABS: { key: BatchTab; label: string }[] = [
  { key: "list", label: "실행 목록" },
  { key: "new", label: "새 일괄 예측" },
];

export function readBatchTab(): BatchTab | null {
  try {
    const v = globalThis.localStorage?.getItem(BATCH_TAB_KEY);
    return v === "list" || v === "new" ? v : null;
  } catch {
    return null;
  }
}

export function writeBatchTab(t: BatchTab) {
  try {
    globalThis.localStorage?.setItem(BATCH_TAB_KEY, t);
  } catch {
    /* 저장 실패는 무시 */
  }
}

/** 완료 run 첫 응답 요약: "MaxStress 1.5 ~ 2.5 MPa (2 run)" */
export function responseSummaryText(b: PredictBatchSummary): string {
  const r = b.response_summary;
  if (!r) return "";
  return `${r.name} ${fmtNum(r.min, 4)} ~ ${fmtNum(r.max, 4)}${r.unit ? ` ${r.unit}` : ""} (${r.count} run)`;
}

/** 상태 집계 한 줄: 입력 생성 x/N · 실행 중 a · 대기 b · 완료 c · 실패 d */
export function batchCountsText(b: PredictBatchSummary): string {
  const g = b.gen;
  const p = b.predict;
  if (!g || !p) return "";
  const parts = [`입력 생성 ${g.done}/${g.total}`];
  if (p.running) parts.push(`실행 중 ${p.running}`);
  if (p.queued) parts.push(`대기 ${p.queued}`);
  parts.push(`완료 ${p.succeeded}`);
  const failed = g.failed + p.failed + p.canceled;
  if (failed) parts.push(`실패 ${failed}`);
  return parts.join(" · ");
}

export function BatchMode() {
  const { study } = useStudy();
  const [list, setList] = useState<PredictBatchSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<BatchTab | null>(null); // null = 목록을 받은 뒤 기본 탭 결정
  const load = useCallback(async () => {
    try {
      setList(await api.batches(study.id));
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
      setList((l) => l ?? []);
    }
  }, [study.id]);
  useEffect(() => {
    void load();
  }, [load]);
  const anyActive = !!list?.some((b) => isBatchActive(b.status));
  usePolling(load, anyActive && tab === "list" ? POLL.batch : null, false, [study.id]);
  useEffect(() => {
    if (tab === null && list !== null) setTab(anyActive ? "list" : readBatchTab() ?? "new");
  }, [list, tab, anyActive]);
  const choose = (t: BatchTab) => {
    setTab(t);
    writeBatchTab(t);
    if (t === "list") void load();
  };
  const cur = tab ?? "new";

  return (
    <>
      <Card span={9} title="일괄 예측" className="batch-tabs">
        <div className="tabs" role="tablist" aria-label="일괄 예측">
          {TABS.map((t) => (
            <button key={t.key} type="button" role="tab" aria-selected={cur === t.key} className={cur === t.key ? "on" : ""} onClick={() => choose(t.key)}>
              {t.label}
              {t.key === "list" && list?.length ? <span className="muted small"> {list.length}</span> : null}
            </button>
          ))}
        </div>
      </Card>
      {tab === null ? (
        <Card span={9} title="실행 목록">
          <p className="muted">불러오는 중…</p>
        </Card>
      ) : cur === "list" ? (
        <BatchList list={list ?? []} error={error} onNew={() => choose("new")} />
      ) : (
        <BatchSetup onStarted={() => writeBatchTab("list")} />
      )}
    </>
  );
}

function BatchList({ list, error, onNew }: { list: PredictBatchSummary[]; error: string | null; onNew: () => void }) {
  const { study } = useStudy();
  const navigate = useNavigate();
  const base = `/p/${study.project_id}/s/${study.id}/stage/4/batch`;
  return (
    <Card span={9} title="실행 목록" className="batch-list">
      {error && <p className="error-text small">{error}</p>}
      {!list.length ? (
        <p className="muted small">
          아직 일괄 예측이 없습니다 —{" "}
          <button type="button" className="btn small ghost" onClick={onNew}>
            새 일괄 예측
          </button>
          에서 시작하세요.
        </p>
      ) : (
        <div className="table-wrap">
          <table className="table compact" aria-label="일괄 예측 실행 목록">
            <thead>
              <tr>
                <th>번호</th>
                <th>템플릿</th>
                <th className="num">조합 수</th>
                <th>상태</th>
                <th>응답 요약</th>
                <th>시작</th>
              </tr>
            </thead>
            <tbody>
              {list.map((b) => (
                <tr key={b.id} className="clickable" data-testid={`batch-${b.label}`} onClick={() => navigate(`${base}/${b.id}`)}>
                  <td>
                    <Link to={`${base}/${b.id}`} onClick={(e) => e.stopPropagation()}>
                      {b.label}
                    </Link>
                  </td>
                  <td className="small">{b.param_set?.label ?? b.param_set?.id ?? "—"}</td>
                  <td className="num">{b.run_count}</td>
                  <td className="small">
                    <span className={`pill ${batchTone(b.status)}`}>{BATCH_STATUS_LABEL[b.status] ?? String(b.status)}</span>
                    <span className="muted"> · {batchCountsText(b)}</span>
                  </td>
                  <td className="small mono" data-testid={`summary-${b.label}`}>
                    {responseSummaryText(b) || <span className="muted">—</span>}
                  </td>
                  <td className="small">
                    {fmtTime(b.created_at)} <span className="muted">{b.created_by_name}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
