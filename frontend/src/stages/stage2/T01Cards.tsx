import { useMemo, useState } from "react";
import type { Job } from "../../api";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Advanced, Card, Field, RunAction } from "../../components/ui";
import { FeatureGate } from "../../components/FeatureGate";
import { Chart } from "../../components/Chart";
import { JsonTree } from "../../components/JsonTree";
import { parseT01Preview, type T01Tree } from "../../lib/curation";
import { sameSource, useCuration } from "./CurationContext";
import { useJobJson } from "./Sources";
import { CurationResult } from "./H3dCards";

export function useT01Preview() {
  const c = useCuration();
  const runner = useJobRunner("CU_T01_PREVIEW");
  const match = !!runner.job && sameSource((runner.job.params as { source?: unknown }).source, c.source);
  const files = useJobJson(match ? runner.job : null, ["PREVIEW_JSON"]);
  const tree = useMemo(() => {
    if (!files) return null;
    const raw = files["PREVIEW_T01.json"] ?? Object.values(files)[0];
    return parseT01Preview(raw);
  }, [files]);
  return { runner, match, tree };
}

// ---------------------------------------------------------------- ②-3
export function T01PreviewCard({ shared }: { shared: ReturnType<typeof useT01Preview> }) {
  const c = useCuration();
  const canExec = useCanExecute();
  const { runner, match, tree } = shared;
  const [sample, setSample] = useState("");
  return (
    <Card step="②-3" title="T01 미리보기">
      <Advanced>
        <Field label="대표 파일(원천 기준 상대경로)" hint="비우면 이름순 첫 파일">
          <input className="mono" value={sample} onChange={(e) => setSample(e.target.value)} aria-label="대표 T01 파일" />
        </Field>
      </Advanced>
      <FeatureGate feature="curation_t01">
        {(enabled) => (
          <RunAction
            canExecute={canExec}
            label="T01 미리보기"
            onRun={() => c.source && void runner.run({ source: c.source, sample_file: sample.trim() || null })}
            job={match ? runner.job : null}
            disabled={!enabled || !c.source || (c.sourceInfo?.t01 ?? 1) === 0}
            disabledReason={enabled ? "원천을 먼저 선택하세요" : undefined}
            error={runner.error}
          />
        )}
      </FeatureGate>
      {tree ? <T01TreeView tree={tree} /> : <p className="muted small">미리보기를 실행하면 Type / Request / Component 트리가 표시됩니다.</p>}
    </Card>
  );
}

function T01TreeView({ tree }: { tree: T01Tree[] }) {
  return (
    <ul className="tree t01-tree" aria-label="T01 트리">
      {tree.map((t) => (
        <li key={t.name}>
          <details open>
            <summary>
              {t.name} <span className="muted small">({t.requests.length})</span>
            </summary>
            <ul className="tree">
              {t.requests.map((r) => (
                <li key={r.name}>
                  <span className="mono">{r.name}</span> <span className="muted small">{r.components.join(", ")}</span>
                </li>
              ))}
            </ul>
          </details>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------- ②-4
interface CurveSel {
  type: string;
  request: string;
  component: string;
}

export function T01CurvesCard({ shared }: { shared: ReturnType<typeof useT01Preview> }) {
  const c = useCuration();
  const canExec = useCanExecute();
  const { tree } = shared;
  const runner = useJobRunner("CU_T01_CURVES", () => void c.reload());
  const [curves, setCurves] = useState<CurveSel[]>([]);
  const [sel, setSel] = useState<CurveSel>({ type: "", request: "", component: "" });

  const types = tree ?? [];
  const t = types.find((x) => x.name === sel.type) ?? types[0];
  const r = t?.requests.find((x) => x.name === sel.request) ?? t?.requests[0];
  const comp = r?.components.includes(sel.component) ? sel.component : r?.components[0] ?? "";
  const add = () => {
    if (!t || !r || !comp) return;
    if (curves.some((x) => x.type === t.name && x.request === r.name && x.component === comp)) return;
    setCurves([...curves, { type: t.name, request: r.name, component: comp }]);
  };

  const latest = c.curations.find((x) => x.kind === "T01" && (x.job_id === runner.job?.id || !runner.job));
  const curveJobId = runner.job?.state === "SUCCEEDED" ? runner.job : latest ? ({ id: latest.job_id, state: "SUCCEEDED" } as Job) : null;

  return (
    <Card step="②-4" title="T01 곡선 추출">
      {!tree ? (
        <p className="muted">②-3 미리보기를 먼저 실행하세요.</p>
      ) : (
        <>
          <table className="table compact" aria-label="곡선 선택">
            <thead>
              <tr>
                <th>Type</th>
                <th>Request</th>
                <th>Component</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {curves.map((cv, i) => (
                <tr key={`${cv.type}|${cv.request}|${cv.component}`}>
                  <td>{cv.type}</td>
                  <td className="mono">{cv.request}</td>
                  <td>{cv.component}</td>
                  <td>
                    <button type="button" className="icon-btn" aria-label="곡선 삭제" onClick={() => setCurves(curves.filter((_, j) => j !== i))}>
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
              <tr className="add-row">
                <td>
                  <select value={t?.name ?? ""} onChange={(e) => setSel({ type: e.target.value, request: "", component: "" })} aria-label="Type 선택" disabled={!canExec}>
                    {types.map((x) => (
                      <option key={x.name}>{x.name}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <select value={r?.name ?? ""} onChange={(e) => setSel({ type: t?.name ?? "", request: e.target.value, component: "" })} aria-label="Request 선택" disabled={!canExec}>
                    {(t?.requests ?? []).map((x) => (
                      <option key={x.name}>{x.name}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <select value={comp} onChange={(e) => setSel({ type: t?.name ?? "", request: r?.name ?? "", component: e.target.value })} aria-label="Component 선택" disabled={!canExec}>
                    {(r?.components ?? []).map((x) => (
                      <option key={x}>{x}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <button type="button" className="btn small" onClick={add} disabled={!canExec || !comp}>
                    추가
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </>
      )}
      <FeatureGate feature="curation_t01">
        {(enabled) => (
          <RunAction
            canExecute={canExec}
            label="곡선 추출"
            onRun={() => c.source && void runner.run({ source: c.source, curves, exclude_files: [] })}
            job={runner.job}
            disabled={!enabled || !c.source || !curves.length}
            disabledReason={enabled ? "곡선을 1개 이상 추가하세요" : undefined}
            error={runner.error}
          />
        )}
      </FeatureGate>
      {latest && <CurationResult cur={latest} />}
      {latest?.status === "READY" && curveJobId && <FirstCurve job={curveJobId} />}
    </Card>
  );
}

interface CurveFile {
  series?: { name: string; x: number[]; y: number[] }[];
}

/** 첫 곡선 미리보기: series가 있으면 SVG 선 그래프, 없으면 JSON 트리 + "곡선 형식 미확인"(U27) */
export function FirstCurve({ job }: { job: Job }) {
  const files = useJobJson(job, ["CURVE_JSON"]);
  if (!files) return null;
  const first = Object.values(files)[0] as CurveFile | undefined;
  if (!first) return <p className="muted small">곡선 파일이 산출물로 등록되지 않았습니다(크기 상한 초과 등).</p>;
  const series = Array.isArray(first.series) ? first.series.filter((s) => Array.isArray(s.x) && Array.isArray(s.y)) : [];
  if (!series.length)
    return (
      <div className="curve" data-testid="curve-unknown">
        <p className="muted small">곡선 형식 미확인</p>
        <JsonTree data={first} />
      </div>
    );
  return (
    <div className="curve" data-testid="curve-chart">
      <div className="field-label">첫 곡선 미리보기</div>
      <Chart
        height={200}
        aspect={0.32}
        maxHeight={460}
        ariaLabel="첫 곡선"
        lines={series.map((s, i) => ({ name: s.name, pts: s.x.map((x, j) => [x, s.y[j]] as [number, number]), className: `chart-line s${i % 4}` }))}
      />
      <div className="legend small">
        {series.map((s, i) => (
          <span key={s.name}>
            <span className={`lg line s${i % 4}`} /> {s.name}
          </span>
        ))}
      </div>
    </div>
  );
}
