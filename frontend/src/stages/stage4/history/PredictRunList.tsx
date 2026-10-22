// ④ 단일 예측 "실행 목록"(phase3 §21.2.3): 표 + 필터 세그먼트(전체|템플릿|준비된 입력) + 더 보기(커서) + 진행 중이면 5초 폴링. 행 → ?job=<job_id>.
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { errorMessage } from "../../../api";
import { predictRunsApi, type PredictRunMode, type PredictRunSummary } from "../../../api/predictRuns";
import { useStudy } from "../../../app/StudyContext";
import { Card, JobStatusBadge } from "../../../components/ui";
import { InputBadge } from "../../../components/InputKindSelect";
import { usePolling } from "../../../hooks/usePolling";
import { POLL } from "../../../lib/poll";
import { MODE_FILTERS, durationText, firstResponseText, isActiveState, mdHm, sourceLabel, valuesText } from "./runListText";

const PAGE = 50;

export function PredictRunList({ initialMode, onNew }: { initialMode: PredictRunMode; onNew: () => void }) {
  const { study } = useStudy();
  const navigate = useNavigate();
  const [mode, setMode] = useState<PredictRunMode>(initialMode);
  const [rows, setRows] = useState<PredictRunSummary[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [more, setMore] = useState(false);
  const seq = useRef(0);

  /** 첫 쪽을 읽는다. 폴링은 첫 쪽만 바꾸고 이미 불러온 뒤 쪽은 남긴다 */
  const load = useCallback(
    async (reset: boolean) => {
      const my = ++seq.current;
      try {
        const r = await predictRunsApi.list(study.id, { mode, limit: PAGE });
        if (my !== seq.current) return;
        setError(null);
        setRows((prev) => {
          if (reset || !prev) return r.items;
          const ids = new Set(r.items.map((x) => x.job_id));
          const tail = prev.slice(r.items.length).filter((x) => !ids.has(x.job_id));
          return [...r.items, ...tail];
        });
        if (reset || !rows || rows.length <= PAGE) setNext(r.nextCursor);
      } catch (e) {
        if (my !== seq.current) return;
        setError(errorMessage(e));
        setRows((p) => p ?? []);
      }
    },
    // rows 길이는 첫 쪽 커서 유지 판단에만 쓰므로 의존에서 뺀다
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [study.id, mode],
  );
  useEffect(() => {
    setRows(null);
    void load(true);
  }, [load]);
  const anyActive = !!rows?.some((r) => isActiveState(r.state));
  usePolling(() => load(false), anyActive ? POLL.batch : null, false, [study.id, mode]);

  const loadMore = async () => {
    if (!next) return;
    setMore(true);
    try {
      const r = await predictRunsApi.list(study.id, { mode, limit: PAGE, cursor: next });
      setRows((prev) => {
        const have = new Set((prev ?? []).map((x) => x.job_id));
        return [...(prev ?? []), ...r.items.filter((x) => !have.has(x.job_id))];
      });
      setNext(r.nextCursor);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setMore(false);
    }
  };

  const filter = (
    <div className="seg" role="group" aria-label="입력 방식 필터">
      {MODE_FILTERS.map((f) => (
        <button key={f.key} type="button" className={mode === f.key ? "on" : ""} aria-pressed={mode === f.key} onClick={() => setMode(f.key)}>
          {f.label}
        </button>
      ))}
    </div>
  );

  return (
    <Card span={9} title="실행 목록" className="predict-run-list" aside={filter}>
      {error && <p className="error-text small" role="alert">{error}</p>}
      {rows === null ? (
        <p className="muted small">불러오는 중…</p>
      ) : !rows.length ? (
        <p className="muted small">
          아직 실행한 예측이 없습니다 —{" "}
          <button type="button" className="btn small ghost" onClick={onNew}>
            새 예측
          </button>
          에서 시작하세요.
        </p>
      ) : (
        <>
          <div className="table-wrap">
            <table className="table compact" aria-label="단일 예측 실행 목록">
              <thead>
                <tr>
                  <th>시작</th>
                  <th>입력 방식</th>
                  <th>입력</th>
                  <th>템플릿 / 입력 파일</th>
                  <th>값</th>
                  <th>응답</th>
                  <th>상태</th>
                  <th className="num">소요</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.job_id} className="clickable" data-testid={`run-${r.job_id}`} onClick={() => navigate(`?job=${r.job_id}`)}>
                    <td className="small">
                      <button type="button" className="link" onClick={(e) => (e.stopPropagation(), navigate(`?job=${r.job_id}`))}>
                        {mdHm(r.started_at ?? r.created_at)}
                      </button>
                      {r.origin === "fem_verify" && <span className="muted small"> · FEM 검증</span>}
                    </td>
                    <td className="small">{r.input_mode === "prepared" ? "준비된 입력" : "템플릿"}</td>
                    <td className="small"><InputBadge input={r.input} /></td>
                    <td className="small ellipsis" title={r.input_path ?? undefined}>
                      {sourceLabel(r)}
                    </td>
                    <td className="small mono">{valuesText(r.values) || <span className="muted">—</span>}</td>
                    <td className="small mono">{firstResponseText(r) || <span className="muted">—</span>}</td>
                    <td className="small">
                      <JobStatusBadge state={r.state} />
                      {r.attempts > 1 && <span className="muted"> · {r.attempts}회차</span>}
                      {r.failure && <span className="error-text small" title={r.failure.message}> {r.failure.code}</span>}
                    </td>
                    <td className="num small">{durationText(r.duration_s)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {next && (
            <div className="run-action-row">
              <button type="button" className="btn small" disabled={more} onClick={loadMore}>
                {more ? "불러오는 중…" : "더 보기"}
              </button>
            </div>
          )}
        </>
      )}
    </Card>
  );
}
