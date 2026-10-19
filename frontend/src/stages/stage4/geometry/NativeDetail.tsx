// ④ native 세트 상세(geometry-engine.md §8): 준비 상태 배지 + "형상 준비 다시", 피처 표(행 클릭 = 하이라이트 PNG),
// 대칭 그룹 분리·묶기(§6.2 symmetry_split), 고급 접힘 2개(검사 기준·다중 baseline) + 쉘 두께 PROP(3S).
import { useEffect, useState } from "react";
import { API_PREFIX, api, errorMessage, type NativeFeatures, type ParamSet } from "../../../api";
import { useStudy } from "../../../app/StudyContext";
import { JobInline } from "../../../components/ui";
import { useLatestJob } from "../../../hooks/useLatestJob";
import { isTerminal } from "../../../lib/format";
import { PREP_LABEL, PREP_TONE, exceedsFeasible, geomErrorText, isSplit, rangeText, toggleSplit, typeLabel } from "../../../lib/geometry";
import { GeomOptionsForm } from "./GeomOptionsForm";
import { ShellProps } from "./ShellProps";
import { MultiBaseline } from "./MultiBaseline";
import { useMediaImage } from "../ContourMedia";

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
  const [picked, setPicked] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
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
  const pickedF = data.features.find((f) => f.name === picked) ?? null;
  return (
    <div className="feature-block">
      <div className="small muted">
        자동 후보 피처 <b>{data.features.length}</b>개{data.engine_version ? ` · paicad ${data.engine_version}` : ""} — 행을 누르면 하이라이트(이동 면 주황·고정 면 파랑)를 봅니다
      </div>
      <div className="table-wrap">
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
                <tr key={f.name} className={`${picked === f.name ? "picked" : ""}${f.ref_locked ? " unused" : ""}`} onClick={() => setPicked(f.name === picked ? null : f.name)} aria-selected={picked === f.name}>
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
                            onClick={(e) => {
                              e.stopPropagation();
                              void split(f.group!);
                            }}
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
      {error && (
        <div className="error-text small" role="alert">
          {error}
        </div>
      )}
      {pickedF?.png_artifact_id && <FeaturePng name={pickedF.name} artifactId={pickedF.png_artifact_id} />}
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

/** 하이라이트 PNG(§4.3 features/<NAME>.png → FEATURE_PNG artifact). 이미지는 fetch → blob URL(목·쿠키 인증 같은 길) */
function FeaturePng({ name, artifactId }: { name: string; artifactId: string }) {
  const src = useMediaImage(`${API_PREFIX}/artifacts/${artifactId}/media`);
  return (
    <figure className="feature-png" data-testid="feature-png">
      {src && <img src={src} alt={`${name} 하이라이트`} />}
      <figcaption className="small muted mono">{name}</figcaption>
    </figure>
  );
}
