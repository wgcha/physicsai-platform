// ④ FEM 검증 목록(phase3 §21.3.11): 표 FV # · 출처 · 설계점(앞 3개) · 상태 · 최대 오차% · 시작 · 등록자. 진행 중이면 5초 폴링, 행 → 상세.
// `?new=1&kind=…`이면 위에 새 검증 카드.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { errorMessage } from "../../../api";
import { femVerifyApi, isFvActive, type FemVerifySummary } from "../../../api/femVerify";
import { useStudy } from "../../../app/StudyContext";
import { Card } from "../../../components/ui";
import { usePolling } from "../../../hooks/usePolling";
import { POLL } from "../../../lib/poll";
import { mdHm, valuesText } from "../history/runListText";
import { VerifyNew } from "./VerifyNew";
import { fvStatusText, fvTone, pctText, sourceFromQuery } from "./verifyRules";
import "../../../styles/femVerify.css";

const PAGE = 50;

export function VerifyList() {
  const { study } = useStudy();
  const navigate = useNavigate();
  const [search] = useSearchParams();
  const base = `/p/${study.project_id}/s/${study.id}/stage/4`;
  const [rows, setRows] = useState<FemVerifySummary[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [more, setMore] = useState(false);
  const seq = useRef(0);

  const load = useCallback(
    async (reset: boolean) => {
      const my = ++seq.current;
      try {
        const r = await femVerifyApi.list(study.id, { limit: PAGE });
        if (my !== seq.current) return;
        setError(null);
        setRows((prev) => {
          if (reset || !prev) return r.items;
          const ids = new Set(r.items.map((x) => x.id));
          return [...r.items, ...prev.slice(r.items.length).filter((x) => !ids.has(x.id))];
        });
        if (reset) setNext(r.nextCursor);
      } catch (e) {
        if (my !== seq.current) return;
        setError(errorMessage(e));
        setRows((p) => p ?? []);
      }
    },
    [study.id],
  );
  useEffect(() => {
    setRows(null);
    void load(true);
  }, [load]);
  const anyActive = !!rows?.some((r) => isFvActive(r.status));
  usePolling(() => load(false), anyActive ? POLL.batch : null, false, [study.id]);

  const loadMore = async () => {
    if (!next) return;
    setMore(true);
    try {
      const r = await femVerifyApi.list(study.id, { limit: PAGE, cursor: next });
      setRows((prev) => {
        const have = new Set((prev ?? []).map((x) => x.id));
        return [...(prev ?? []), ...r.items.filter((x) => !have.has(x.id))];
      });
      setNext(r.nextCursor);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setMore(false);
    }
  };

  const newSource = search.get("new") === "1" ? sourceFromQuery(search) : null;
  const newBad = search.get("new") === "1" && !newSource;

  return (
    <>
      {newSource && <VerifyNew key={JSON.stringify(newSource)} source={newSource} base={base} />}
      {newBad && (
        <Card span={9} title="새 FEM 검증">
          <p className="muted small">검증 대상이 올바르지 않습니다 — ④ 예측·⑤ 결과분석·⑥ 최적화의 “FEM 검증” 버튼으로 시작하세요.</p>
        </Card>
      )}
      <Card span={9} title="FEM 검증" className="fv-list" aside={<Link className="small" to={base}>← ④ 예측</Link>}>
        {error && <p className="error-text small" role="alert">{error}</p>}
        {rows === null ? (
          <p className="muted small">불러오는 중…</p>
        ) : !rows.length ? (
          <p className="muted small">아직 FEM 검증이 없습니다 — 예측 결과의 “FEM 검증” 버튼으로 시작하세요.</p>
        ) : (
          <>
            <div className="table-wrap">
              <table className="table compact" aria-label="FEM 검증 목록">
                <thead>
                  <tr>
                    <th>FV #</th>
                    <th>출처</th>
                    <th>설계점</th>
                    <th>상태</th>
                    <th className="num">최대 오차%</th>
                    <th>시작</th>
                    <th>등록자</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id} className="clickable" data-testid={`fv-${r.label}`} onClick={() => navigate(`${base}/verify/${r.id}`)}>
                      <td>
                        <Link to={`${base}/verify/${r.id}`} onClick={(e) => e.stopPropagation()}>
                          {r.label}
                        </Link>
                      </td>
                      <td className="small">{r.source_label}</td>
                      <td className="small mono">{valuesText(r.values ?? {}) || <span className="muted">—</span>}</td>
                      <td className="small">
                        <span className={`pill ${fvTone(r.status)}`}>{fvStatusText(r)}</span>
                      </td>
                      <td className="num small">{r.status === "DONE" && r.max_abs_diff_pct != null ? <>{pctText(r.max_abs_diff_pct)}{r.worst ? <span className="muted"> ({r.worst})</span> : null}</> : <span className="muted">—</span>}</td>
                      <td className="small">{mdHm(r.created_at)}</td>
                      <td className="small">{r.created_by_name}</td>
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
    </>
  );
}
