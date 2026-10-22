// ⑤ 플랫폼 내장 최적화(phase3.md §18.10): 서브 탭 "실행 목록" | "새 최적화"(D3-53 ④와 같은 규칙 — 진행 중이 있으면 실행 목록 기본).
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { errorMessage } from "../../../api";
import { isSoActive, surrogateApi, type SurrogateOptSummary } from "../../../api/surrogateOpt";
import { useStudy } from "../../../app/StudyContext";
import { Card } from "../../../components/ui";
import { InputBadge } from "../../../components/InputKindSelect";
import { usePolling } from "../../../hooks/usePolling";
import { fmtNum, fmtTime } from "../../../lib/format";
import { POLL } from "../../../lib/poll";
import { SurrogateSetup } from "./SurrogateSetup";
import { SO_STATUS_LABEL, SO_TAB_KEY, metricLabel, soTone } from "./soRules";

type Tab = "list" | "new";

function readTab(): Tab | null {
  try {
    const v = globalThis.localStorage?.getItem(SO_TAB_KEY);
    return v === "list" || v === "new" ? v : null;
  } catch {
    return null;
  }
}
function writeTab(t: Tab) {
  try {
    globalThis.localStorage?.setItem(SO_TAB_KEY, t);
  } catch {
    /* 무시 */
  }
}

export function SurrogateMode() {
  const { study } = useStudy();
  const [list, setList] = useState<SurrogateOptSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab | null>(null);
  const load = useCallback(async () => {
    try {
      setList(await surrogateApi.list(study.id));
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
      setList((l) => l ?? []);
    }
  }, [study.id]);
  useEffect(() => {
    void load();
  }, [load]);
  const anyActive = !!list?.some((o) => isSoActive(o.status));
  usePolling(load, anyActive && tab === "list" ? POLL.surrogate : null, false, [study.id]);
  useEffect(() => {
    if (tab === null && list !== null) setTab(anyActive ? "list" : readTab() ?? "new");
  }, [list, tab, anyActive]);
  const choose = (t: Tab) => {
    setTab(t);
    writeTab(t);
    if (t === "list") void load();
  };
  const cur = tab ?? "new";
  return (
    <>
      <Card span={9} title="플랫폼 내장 최적화" className="batch-tabs">
        <div className="tabs" role="tablist" aria-label="내장 최적화">
          {(["list", "new"] as const).map((k) => (
            <button key={k} type="button" role="tab" aria-selected={cur === k} className={cur === k ? "on" : ""} onClick={() => choose(k)}>
              {k === "list" ? "실행 목록" : "새 최적화"}
              {k === "list" && list?.length ? <span className="muted small"> {list.length}</span> : null}
            </button>
          ))}
        </div>
      </Card>
      {tab === null ? (
        <Card span={9} title="실행 목록"><p className="muted">불러오는 중…</p></Card>
      ) : cur === "list" ? (
        <SoList list={list ?? []} error={error} onNew={() => choose("new")} />
      ) : (
        <SurrogateSetup active={anyActive} onStarted={() => writeTab("list")} />
      )}
    </>
  );
}

function SoList({ list, error, onNew }: { list: SurrogateOptSummary[]; error: string | null; onNew: () => void }) {
  const { study } = useStudy();
  const navigate = useNavigate();
  const base = `/p/${study.project_id}/s/${study.id}/stage/5/surrogate`;
  return (
    <Card span={9} title="실행 목록" className="batch-list">
      {error && <p className="error-text small">{error}</p>}
      {!list.length ? (
        <p className="muted small">
          아직 내장 최적화가 없습니다 —{" "}
          <button type="button" className="btn small ghost" onClick={onNew}>새 최적화</button>
          에서 시작하세요.
        </p>
      ) : (
        <div className="table-wrap">
          <table className="table compact" aria-label="내장 최적화 실행 목록">
            <thead>
              <tr>
                <th>번호</th>
                <th>목적</th>
                <th>입력</th>
                <th>상태</th>
                <th className="num">반복</th>
                <th className="num">최적 값</th>
                <th>시작</th>
              </tr>
            </thead>
            <tbody>
              {list.map((o) => {
                const obj = o.objective as { metric: string; series?: string | null; sense: string };
                return (
                  <tr key={o.id} className="clickable" data-testid={`so-${o.label}`} onClick={() => navigate(`${base}/${o.id}`)}>
                    <td><Link to={`${base}/${o.id}`} onClick={(e) => e.stopPropagation()}>{o.label}</Link></td>
                    <td className="small">{metricLabel(obj.metric, obj.series)} <span className="muted">{obj.sense === "max" ? "최대화" : "최소화"}</span></td>
                    <td className="small"><InputBadge input={o.input} /></td>
                    <td className="small"><span className={`pill ${soTone(o.status)}`}>{SO_STATUS_LABEL[o.status] ?? o.status}</span></td>
                    <td className="num">{o.iter_no}/{o.iterations}</td>
                    <td className="num mono">{fmtNum(o.best_value)}</td>
                    <td className="small">{fmtTime(o.created_at)} <span className="muted">{o.created_by_name}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
