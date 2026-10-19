// ④ native 세트 "다중 baseline(고급)"(geometry-engine.md §8·§4.10·§7.3.8·§11.4): 접힘 1개, 기본 닫힘 — 켜지 않으면 화면 변경 없음.
// baseline 추가(경로 고르기 = 기존 discover 후보 재사용)·삭제, 자동 매칭표(등급 색·점수, 행별 수락/변경/분리·N/A, 재확인 배지),
// 상단 [확정] 1개 + 상태 배지 초안/확정(사용자·시각). API는 백엔드 병합 전 목 라우트(계약 §7.3.8 모양).
import { useEffect, useState } from "react";
import { api, errorMessage, type MapDecision, type MapRow, type ParamMap, type ParamSet, type ParamSetDiscover } from "../../../api";
import { useStudy } from "../../../app/StudyContext";
import { Advanced, JobInline } from "../../../components/ui";
import { BrowseButton } from "../../../components/BrowseButton";
import { useLatestJob } from "../../../hooks/useLatestJob";
import { fmtTime, isTerminal } from "../../../lib/format";
import { GEOM_ERROR_TEXT, GRADE_LABEL, GRADE_TONE, effectiveMap, effectiveName, fmtScore, nameConflicts, pendingRows } from "../../../lib/geometry";

const ACTION_LABEL: Record<MapDecision["action"], string> = { accept: "수락", rename: "변경", change: "변경", split: "분리" };
const NA = "__na__";

export function MultiBaseline({ ps, canEdit }: { ps: ParamSet; canEdit: boolean }) {
  const multi = (ps.baselines?.length ?? 0) > 1;
  return (
    <Advanced label="다중 baseline(고급)">
      <div className="multi-bl" data-testid="multi-baseline">
        <BaselineList ps={ps} canEdit={canEdit} />
        {multi ? <MatchTable key={(ps.baselines ?? []).map((b) => b.id).join(",")} ps={ps} canEdit={canEdit} /> : <p className="muted small">단일 baseline(기본). baseline을 추가하면 공통 변수 매칭표가 만들어집니다.</p>}
      </div>
    </Advanced>
  );
}

function BaselineList({ ps, canEdit }: { ps: ParamSet; canEdit: boolean }) {
  const { study, reloadParamSets } = useStudy();
  const job = useLatestJob(study.id, "PARAM_SET_NATIVE", (j) => j.state === "SUCCEEDED" && void reloadParamSets());
  const [bid, setBid] = useState("");
  const [path, setPath] = useState("");
  const [found, setFound] = useState<ParamSetDiscover | null>(null);
  const [cad, setCad] = useState("");
  const [assem, setAssem] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const running = !!job.job && !isTerminal(job.job.state);

  const find = async () => {
    setError(null);
    setBusy(true);
    try {
      const d = await api.discoverParamSet(study.id, path.trim(), null, "native");
      setFound(d);
      setCad(d.cad.length === 1 ? d.cad[0].rel : "");
      setAssem(d.radioss_assem.length === 1 ? d.radioss_assem[0].rel : "");
    } catch (e) {
      setFound(null);
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const add = async () => {
    if (!found) return;
    setError(null);
    setBusy(true);
    try {
      const r = await api.addBaseline(ps.id, { id: bid.trim(), path: found.path, choice: { cad, radioss_assem: assem } });
      job.track(await api.job(r.job_id));
      setFound(null);
      setPath("");
      setBid("");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };
  const remove = async (id: string) => {
    setError(null);
    try {
      await api.deleteBaseline(ps.id, id);
      await reloadParamSets();
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  const ready = !!found && !found.problems.length && !!cad && !!assem && /^[A-Za-z0-9_-]{1,32}$/.test(bid.trim()) && !running;

  return (
    <div className="bl-list">
      {ps.baselines?.length ? (
        <ul className="plain small" aria-label="baseline 목록">
          {ps.baselines.map((b) => (
            <li key={b.id} className="run-action-row">
              <span className="mono">{b.id}</span>
              {b.label && <span>{b.label}</span>}
              {b.prep_status && b.prep_status !== "READY" && <span className="pill warn">다시 준비 필요</span>}
              {b.source_path && <span className="muted mono ellipsis">{b.source_path}</span>}
              {canEdit && b.id !== "base" && (
                <button type="button" className="btn small ghost" onClick={() => void remove(b.id)}>
                  삭제
                </button>
              )}
            </li>
          ))}
        </ul>
      ) : null}
      {canEdit && (
        <div className="bl-add">
          <div className="pathinput-row">
            <input type="text" className="mono bl-id" value={bid} placeholder="B2" aria-label="baseline id" maxLength={32} onChange={(e) => setBid(e.target.value)} />
            <input
              type="text"
              className="mono"
              value={path}
              placeholder="baseline 프로젝트 폴더(STEP + 조립 폴더)"
              aria-label="baseline 폴더 경로"
              spellCheck={false}
              onChange={(e) => {
                setPath(e.target.value);
                setFound(null);
              }}
            />
            <BrowseButton mode="dir" value={path} onPick={(v) => (setPath(v), setFound(null))} disabled={busy} title="baseline 폴더 선택" />
            <button type="button" className="btn small" disabled={busy || !path.trim()} onClick={() => void find()}>
              찾기
            </button>
          </div>
          {found && (
            <div className="run-action-row small">
              {found.problems.length ? (
                <span className="error-text">{found.problems.map((p) => p.message).join(" · ")}</span>
              ) : (
                <>
                  <select aria-label="baseline CAD" value={cad} onChange={(e) => setCad(e.target.value)}>
                    {found.cad.length > 1 && <option value="">CAD 선택</option>}
                    {found.cad.map((c) => (
                      <option key={c.rel} value={c.rel}>
                        {c.rel}
                      </option>
                    ))}
                  </select>
                  <select aria-label="baseline 조립 폴더" value={assem} onChange={(e) => setAssem(e.target.value)}>
                    {found.radioss_assem.length > 1 && <option value="">조립 폴더 선택</option>}
                    {found.radioss_assem.map((a) => (
                      <option key={a.rel} value={a.rel}>
                        {a.rel}
                      </option>
                    ))}
                  </select>
                </>
              )}
            </div>
          )}
          <div className="run-action-row">
            <button type="button" className="btn small" disabled={!ready || busy} onClick={() => void add()}>
              baseline 추가
            </button>
            {job.job && (running || (job.job.params as { mode?: string } | null)?.mode === "add_baseline") && <JobInline job={job.job} />}
          </div>
        </div>
      )}
      {error && (
        <div className="error-text small" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}

function MatchTable({ ps, canEdit }: { ps: ParamSet; canEdit: boolean }) {
  const [map, setMap] = useState<ParamMap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [edit, setEdit] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    api
      .paramMap(ps.id)
      .then((m) => alive && setMap(m))
      .catch((e) => alive && setError(errorMessage(e)));
    return () => {
      alive = false;
    };
  }, [ps.id]);
  if (!map) return error ? <p className="error-text small">{error}</p> : <p className="muted small">매칭표 불러오는 중…</p>;

  const decide = async (row_id: string, decision: MapDecision | null) => {
    setError(null);
    try {
      setMap(await api.putParamMap(ps.id, [{ row_id, decision }]));
      setEdit(null);
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  const confirm = async () => {
    setError(null);
    try {
      setMap(await api.confirmParamMap(ps.id));
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  const pend = pendingRows(map);
  const conflicts = nameConflicts(map);
  const confirmed = map.status === "confirmed";
  const bl = map.baselines.map((b) => b.id);

  return (
    <div className="match-block">
      <div className="run-action-row">
        <span className={`pill${confirmed ? " ok" : ""}`} data-testid="map-status">
          {confirmed ? `확정(${map.confirmed_by ?? "–"} · ${fmtTime(map.confirmed_at)})` : "초안"}
        </span>
        {canEdit && (
          <button type="button" className="btn small primary" disabled={confirmed || pend.length > 0 || conflicts.size > 0} onClick={() => void confirm()}>
            확정
          </button>
        )}
        {!confirmed && (
          <span className="muted small">
            {pend.length ? `결정하지 않은 행 ${pend.length}개(재확인·확인 필요) · ` : ""}
            {GEOM_ERROR_TEXT.PARAM_MAP_UNCONFIRMED} — 확정 전에는 DOE·일괄 생성을 할 수 없습니다
          </span>
        )}
      </div>
      {map.range_split && (
        <div className="small muted">
          범위 분할 <span className="mono">{map.range_split.param}</span>:{" "}
          {map.range_split.intervals.map((iv) => `${iv.baseline} ${iv.nominal}`).join(" · ")}
        </div>
      )}
      <div className="table-wrap">
        <table className="table compact match-table" aria-label="공통 변수 매칭표">
          <thead>
            <tr>
              <th>공통 변수</th>
              {bl.map((b) => (
                <th key={b} className="mono">
                  {b}
                </th>
              ))}
              <th>등급 · 점수</th>
              <th>결정</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {map.common.map((r) => (
              <Row key={r.row_id} r={r} bl={bl} params={map.params ?? {}} conflict={conflicts.has(r.row_id)} canEdit={canEdit} editing={edit === r.row_id} onEdit={setEdit} onDecide={decide} />
            ))}
          </tbody>
        </table>
      </div>
      {error && (
        <div className="error-text small" role="alert">
          {error}
        </div>
      )}
    </div>
  );
}

function Row({
  r, bl, params, conflict, canEdit, editing, onEdit, onDecide,
}: {
  r: MapRow;
  bl: string[];
  params: Record<string, string[]>;
  conflict: boolean;
  canEdit: boolean;
  editing: boolean;
  onEdit: (id: string | null) => void;
  onDecide: (id: string, d: MapDecision | null) => Promise<void>;
}) {
  const eff = effectiveMap(r);
  const [name, setName] = useState(effectiveName(r));
  const [m, setM] = useState<Record<string, string>>(() => Object.fromEntries(bl.map((b) => [b, eff[b] ?? NA])));
  const g = r.proposed.grade;
  return (
    <>
      <tr data-testid={`map-row-${r.row_id}`}>
        <td>
          <span className="mono">{effectiveName(r)}</span>
          {r.needs_review && <span className="pill warn">재확인</span>}
          {conflict && <span className="error-text small"> 이름 충돌</span>}
        </td>
        {bl.map((b) => (
          <td key={b} className="mono small">
            {eff[b] ?? <span className="muted">N/A</span>}
          </td>
        ))}
        <td>
          <span className={`pill ${GRADE_TONE[g]}`} data-grade={g}>
            {GRADE_LABEL[g]} {fmtScore(r.proposed.score)}
          </span>
        </td>
        <td className="small">{r.decision ? ACTION_LABEL[r.decision.action] : <span className="muted">미결정</span>}</td>
        <td>
          {canEdit && (
            <span className="run-action-row">
              <button type="button" className="btn small ghost" onClick={() => void onDecide(r.row_id, { action: "accept", name: r.proposed.name, map: r.proposed.map })}>
                수락
              </button>
              <button type="button" className="btn small ghost" aria-expanded={editing} onClick={() => onEdit(editing ? null : r.row_id)}>
                변경
              </button>
              <button type="button" className="btn small ghost" disabled={Object.values(eff).filter(Boolean).length < 2} onClick={() => void onDecide(r.row_id, { action: "split", name: effectiveName(r), map: eff })}>
                분리
              </button>
            </span>
          )}
        </td>
      </tr>
      {editing && (
        <tr className="map-edit">
          <td>
            <input className="mono" aria-label={`${r.row_id} 공통 이름`} value={name} onChange={(e) => setName(e.target.value)} />
          </td>
          {bl.map((b) => (
            <td key={b}>
              <select aria-label={`${r.row_id} ${b} 대응`} value={m[b]} onChange={(e) => setM((x) => ({ ...x, [b]: e.target.value }))}>
                <option value={NA}>N/A</option>
                {[...new Set([...(params[b] ?? []), ...(eff[b] ? [eff[b] as string] : [])])].map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </td>
          ))}
          <td colSpan={3}>
            <button
              type="button"
              className="btn small"
              disabled={!/^[A-Za-z_][A-Za-z0-9_]{0,63}$/.test(name.trim())}
              onClick={() => void onDecide(r.row_id, { action: "change", name: name.trim(), map: Object.fromEntries(bl.map((b) => [b, m[b] === NA ? null : m[b]])) })}
            >
              적용
            </button>
          </td>
        </tr>
      )}
    </>
  );
}
