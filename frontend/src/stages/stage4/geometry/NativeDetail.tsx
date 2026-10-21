// ④ native 세트 상세(geometry-engine.md §8): 준비 상태 배지 + "형상 준비 다시", 피처 표(행 클릭 = 하이라이트 PNG),
// 대칭 그룹 분리·묶기(§6.2 symmetry_split), 고급 접힘 2개(검사 기준·다중 baseline) + 쉘 두께 PROP(3S).
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, errorMessage, type NativeFeatures, type ParamSet } from "../../../api";
import { useStudy } from "../../../app/StudyContext";
import { JobInline } from "../../../components/ui";
import { useLatestJob } from "../../../hooks/useLatestJob";
import { isTerminal } from "../../../lib/format";
import { PREP_LABEL, PREP_TONE, exceedsFeasible, geomErrorText, isSplit, rangeText, toggleSplit, typeLabel } from "../../../lib/geometry";
import { GeomOptionsForm } from "./GeomOptionsForm";
import { ShellProps } from "./ShellProps";
import { MultiBaseline } from "./MultiBaseline";
import { GeomView3DLazy as GeomView3D } from "../geomview/GeomView3DLazy";
import { ViewSplit } from "../geomview/ViewSplit";
import { useRowSelection } from "../geomview/selection";
import { AppliedFilter } from "../../../components/AppliedFilter";

export function NativeDetail({ ps, canEdit }: { ps: ParamSet; canEdit: boolean }) {
  const { study, reloadParamSets } = useStudy();
  const prep = ps.native?.prep_status ?? "MISSING";
  const job = useLatestJob(study.id, "PARAM_SET_NATIVE", (j) => j.state === "SUCCEEDED" && void reloadParamSets());
  const [error, setError] = useState<string | null>(null);
  const reprep = async () => {
    setError(null);
    try {
      const r = await api.nativePrepare(ps.id);
      job.track(await api.job(r.job_id));
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  const running = !!job.job && !isTerminal(job.job.state);
  return (
    <div className="native-detail" data-testid="native-detail">
      <div className="run-action-row">
        <span className={`pill ${PREP_TONE[prep]}`} data-testid="prep-status">
          {PREP_LABEL[prep]}
        </span>
        {ps.native?.prep_reason && <span className="muted small">{ps.native.prep_reason}</span>}
        {canEdit && (
          <button type="button" className={`btn small${prep === "READY" ? " ghost" : ""}`} disabled={running} onClick={() => void reprep()}>
            형상 준비 다시
          </button>
        )}
        {job.job && (running || job.job.params?.param_set_id === ps.id) && <JobInline job={job.job} />}
        {error && (
          <span className="error-text small" role="alert">
            {error}
          </span>
        )}
      </div>
      <FeatureTable key={`${ps.id}-${prep}`} ps={ps} canEdit={canEdit} />
      <ShellProps key={`p-${ps.id}`} ps={ps} canEdit={canEdit} />
      <GeomOptionsForm key={`o-${ps.id}`} ps={ps} canEdit={canEdit} />
      <MultiBaseline key={`b-${ps.id}`} ps={ps} canEdit={canEdit} />
    </div>
  );
}

function FeatureTable({ ps, canEdit }: { ps: ParamSet; canEdit: boolean }) {
  const { reloadParamSets } = useStudy();
  const [data, setData] = useState<NativeFeatures | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const order = useMemo(() => data?.features.map((f) => f.name) ?? [], [data]);
  const sel = useRowSelection(order); // 행 클릭 = 단일, Ctrl/⌘ = 추가, Shift = 범위 · 3D 면 클릭 → 행 선택·표 내부 스크롤(geometry-view.md §7.2)
  const loadView = useCallback(() => api.paramSetView(ps.id), [ps.id]);
  useEffect(() => {
    let alive = true;
    api
      .paramSetFeatures(ps.id)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setLoadError(errorMessage(e)));
    return () => {
      alive = false;
    };
  }, [ps.id]);
  if (loadError) return <p className="muted small">{loadError}</p>;
  if (!data) return <p className="muted small">피처 불러오는 중…</p>;
  const userRange = new Map(ps.parameters.map((p) => [p.name, p]));
  const groups = new Map(data.groups.map((g) => [g.id ?? "", g]));
  const split = async (gid: string) => {
    setError(null);
    try {
      const next = toggleSplit(ps.geom_options, gid);
      await api.patchParamSet(ps.id, { geom_options: Object.keys(next).length ? next : null });
      await reloadParamSets();
    } catch (e) {
      setError(errorMessage(e));
    }
  };
  return (
    <div className="feature-block">
      <AppliedFilter filter={ps.native?.extract_filter ?? data.filter} note="조건을 바꾸려면 새 세트로 등록하세요" />
      <div className="small muted">
        자동 후보 피처 <b>{data.features.length}</b>개{data.engine_version ? ` · paicad ${data.engine_version}` : ""} — 행을 누르면 3D에 표시(Ctrl/⌘ = 추가, Shift = 범위)
        {sel.rows.length > 0 && (
          <button type="button" className="btn small ghost" onClick={sel.clear}>
            선택 해제
          </button>
        )}
      </div>
      <ViewSplit
        view={
          <GeomView3D
            loadKey={ps.id}
            load={loadView}
            rows={sel.rows}
            hover={sel.hover}
            onRows={sel.from3d}
            pngOf={(r) => data.features.find((f) => f.name === r)?.png_artifact_id ?? null}
            firstRow={data.features[0]?.name ?? null}
            paramSetId={ps.id}
            userRanges={Object.fromEntries(ps.parameters.map((p) => [p.name, { min: p.min, max: p.max }]))}
            canPreview={canEdit}
          />
        }
        table={
      <div className="table-wrap" ref={sel.tableRef}>
        <table className="table compact feature-table" aria-label="형상 피처 표">
          <thead>
            <tr>
              <th>사용</th>
              <th>이름</th>
              <th>종류</th>
              <th>바디</th>
              <th className="num">공칭</th>
              <th>범위</th>
              <th>모핑 가능 범위</th>
              <th>대칭 그룹</th>
              <th>기준면</th>
            </tr>
          </thead>
          <tbody>
            {data.features.map((f) => {
              const u = userRange.get(f.name);
              const min = u?.min ?? f.min;
              const max = u?.max ?? f.max;
              const over = exceedsFeasible(min, max, f.feasible);
              const g = f.group ? groups.get(f.group) : undefined;
              const gSplit = isSplit(ps.geom_options, f.group);
              return (
                <tr key={f.name} {...sel.rowProps(f.name)} className={`${sel.rowProps(f.name).className}${f.ref_locked ? " unused" : ""}`}>
                  <td>{f.ref_locked ? <span className="muted small">제외(기본)</span> : "사용"}</td>
                  <td className="mono">{f.name}</td>
                  <td>{typeLabel(f.type)}</td>
                  <td className="mono small">{f.body}</td>
                  <td className="num mono">{f.nominal ?? "–"}</td>
                  <td className="mono small">
                    {rangeText(f.nominal, min, max, f.type)}
                    {over && (
                      <span className="pill warn" title="모핑 가능 범위를 넘으면 일부 샘플이 형상 생성에 실패할 수 있습니다(저장은 허용)">
                        가능 범위 초과
                      </span>
                    )}
                  </td>
                  <td className="mono small">{f.feasible ? `${f.feasible.min ?? "–"} ~ ${f.feasible.max ?? "–"}` : "–"}</td>
                  <td className="small">
                    {f.group ? (
                      <span className="run-action-row">
                        <span className="mono">{f.group}</span>
                        {g && <span className="muted">{gSplit ? "분리됨" : `${g.members.length}개 묶음`}</span>}
                        {canEdit && (
                          <button
                            type="button"
                            className="btn small ghost"
                            onClick={() => void split(f.group!)}
                          >
                            {gSplit ? "묶기" : "분리"}
                          </button>
                        )}
                      </span>
                    ) : (
                      "–"
                    )}
                  </td>
                  <td className="small">{f.ref_locked ? "변경 불가(양면 접촉)" : "자동"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
        }
      />
      {error && (
        <div className="error-text small" role="alert">
          {error}
        </div>
      )}
      {data.warnings.length > 0 && (
        <ul className="problems small muted" aria-label="피처 경고">
          {data.warnings.map((w, i) => (
            <li key={i}>
              {w.feature ? <span className="mono">{w.feature}</span> : null} {geomErrorText(w.code, w.message)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
