import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type Curation, type CurationFile } from "../../api";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Advanced, Card, CodeLine, Field, RunAction } from "../../components/ui";
import { FeatureGate } from "../../components/FeatureGate";
import { parseH3dPreview, timeStepsText, type H3dPreview } from "../../lib/curation";
import { sameSource, useCuration } from "./CurationContext";
import { useJobJson } from "./Sources";

/** 최근 h3d 미리보기 작업 + 지금 원천과 일치할 때만 결과 */
function useH3dPreview() {
  const c = useCuration();
  const runner = useJobRunner("CU_H3D_PREVIEW");
  const match = !!runner.job && sameSource((runner.job.params as { source?: unknown }).source, c.source);
  const files = useJobJson(match ? runner.job : null, ["PREVIEW_JSON"]);
  const preview = useMemo(() => (files ? parseH3dPreview(files) : null), [files]);
  return { runner, match, preview };
}

// ---------------------------------------------------------------- ②-1
export function H3dPreviewCard({ shared }: { shared: ReturnType<typeof useH3dPreview> }) {
  const c = useCuration();
  const canExec = useCanExecute();
  const { runner, match, preview } = shared;
  const [sample, setSample] = useState("");
  return (
    <Card step="②-1" title="h3d 구조 미리보기">
      <Advanced>
        <Field label="대표 파일(원천 기준 상대경로)" hint="비우면 이름순 첫 파일">
          <input className="mono" value={sample} onChange={(e) => setSample(e.target.value)} aria-label="대표 파일" />
        </Field>
      </Advanced>
      <FeatureGate feature="curation_h3d">
        {(enabled) => (
          <RunAction
            canExecute={canExec}
            label="h3d 미리보기"
            onRun={() => c.source && void runner.run({ source: c.source, sample_file: sample.trim() || null })}
            job={match ? runner.job : null}
            disabled={!enabled || !c.source || (c.sourceInfo?.h3d ?? 1) === 0}
            disabledReason={enabled ? "원천을 먼저 선택하세요" : undefined}
            error={runner.error}
          />
        )}
      </FeatureGate>
      {preview ? (
        <div className="kv-row small" data-testid="h3d-preview-summary">
          <span className="kv">
            DataType <b>{preview.datatypes.length}</b>
          </span>
          <span className="kv">
            Part shell <b>{preview.parts.shell.length}</b> · solid <b>{preview.parts.solid.length}</b> · rbody <b>{preview.parts.rbody.length}</b>
          </span>
          <span className="kv">
            Time Step <b>{preview.numSteps}</b>
          </span>
          {preview.sampleFile && <span className="mono muted ellipsis">{preview.sampleFile}</span>}
        </div>
      ) : (
        <p className="muted small">{c.source ? "선택한 원천으로 미리보기를 실행하면 DataType·Part·Time Step이 표시됩니다." : "원천을 먼저 선택하세요."}</p>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- ②-2
function PartList({ label, ids, value, onChange }: { label: string; ids: number[]; value: number[]; onChange: (v: number[]) => void }) {
  return (
    <fieldset className="partlist">
      <legend>
        {label} <span className="muted small">{value.length ? `${value.length}/${ids.length}` : `전체 ${ids.length}`}</span>
      </legend>
      {ids.length === 0 ? (
        <span className="muted small">없음</span>
      ) : (
        <div className="partlist-items">
          {ids.map((id) => (
            <label key={id} className="check small">
              <input type="checkbox" checked={value.includes(id)} onChange={(e) => onChange(e.target.checked ? [...value, id] : value.filter((x) => x !== id))} aria-label={`${label} ${id}`} /> {id}
            </label>
          ))}
        </div>
      )}
    </fieldset>
  );
}

export function H3dCurateCard({ shared }: { shared: ReturnType<typeof useH3dPreview> }) {
  const { projectId = "", studyId = "" } = useParams();
  const c = useCuration();
  const canExec = useCanExecute();
  const { runner: prevRunner, preview } = shared;
  const runner = useJobRunner("CU_H3D_CURATE", () => void c.reload());
  const [items, setItems] = useState<{ datatype: string; component: string }[]>([]);
  const [dt, setDt] = useState("");
  const [comp, setComp] = useState("");
  const [parts, setParts] = useState<{ shell: number[]; solid: number[]; rbody: number[] }>({ shell: [], solid: [], rbody: [] });
  const [inc, setInc] = useState(1);
  const [excluded, setExcluded] = useState<Set<string>>(new Set());

  const choices = (preview?.datatypes ?? []).filter((d) => d.name !== "Displacement" && d.usable.length > 0);
  const curDt = choices.find((d) => d.name === dt) ?? choices[0];
  const compChoices = (curDt?.usable ?? []).filter((x) => !items.some((i) => i.datatype === curDt?.name && i.component === x));

  useEffect(() => {
    setItems([]);
    setParts({ shell: [], solid: [], rbody: [] });
    setExcluded(new Set());
  }, [prevRunner.job?.id]);

  const add = () => {
    if (!curDt) return;
    const cc = compChoices.includes(comp) ? comp : compChoices[0];
    if (!cc) return;
    setItems([...items, { datatype: curDt.name, component: cc }]);
  };

  const disp = preview?.datatypes.find((d) => d.name === "Displacement");
  const submit = () => {
    if (!c.source || !prevRunner.job) return;
    // Displacement는 항상 자동 추가(§6.8). 다른 행이 없으면 Displacement 행 하나로 items ≥1을 채운다
    const sendItems = items.length ? items : [{ datatype: "Displacement", component: disp?.usable[0] ?? "Mag" }];
    void runner.run({
      source: c.source,
      preview_job_id: prevRunner.job.id,
      selection: { items: sendItems, parts, time_increment: inc },
      exclude_files: [...excluded],
    });
  };

  const latest: Curation | undefined = c.curations.find((x) => x.kind === "H3D" && (x.job_id === runner.job?.id || !runner.job));
  const files = preview?.files ?? null;

  return (
    <Card step="②-2" title="h3d 큐레이션" className="curate-card">
      {!preview ? (
        <p className="muted">②-1 미리보기를 먼저 실행하세요. DataType·Component 목록은 미리보기 결과에서 고릅니다.</p>
      ) : (
        <>
          <div className="field-label">DataType · Component</div>
          <table className="table compact" aria-label="DataType Component 표">
            <thead>
              <tr>
                <th>DataType</th>
                <th>Component</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((it, i) => (
                <tr key={`${it.datatype}|${it.component}`}>
                  <td>{it.datatype}</td>
                  <td>{it.component}</td>
                  <td>
                    <button type="button" className="icon-btn" aria-label={`${it.datatype} ${it.component} 삭제`} onClick={() => setItems(items.filter((_, j) => j !== i))}>
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
              <tr className="fixed-row" data-testid="displacement-row">
                <td>Displacement</td>
                <td className="muted">항상 포함</td>
                <td />
              </tr>
              <tr className="add-row">
                <td>
                  <select value={curDt?.name ?? ""} onChange={(e) => setDt(e.target.value)} aria-label="DataType 선택" disabled={!canExec}>
                    {choices.map((d) => (
                      <option key={d.name}>{d.name}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <select value={compChoices.includes(comp) ? comp : compChoices[0] ?? ""} onChange={(e) => setComp(e.target.value)} aria-label="Component 선택" disabled={!canExec}>
                    {compChoices.map((x) => (
                      <option key={x}>{x}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <button type="button" className="btn small" onClick={add} disabled={!canExec || !compChoices.length}>
                    추가
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
          <div className="parts-grid">
            <PartList label="Shell" ids={preview.parts.shell} value={parts.shell} onChange={(v) => setParts({ ...parts, shell: v })} />
            <PartList label="Solid" ids={preview.parts.solid} value={parts.solid} onChange={(v) => setParts({ ...parts, solid: v })} />
            <PartList label="Rbody" ids={preview.parts.rbody} value={parts.rbody} onChange={(v) => setParts({ ...parts, rbody: v })} />
          </div>
          <p className="muted small">Part를 비우면 전체를 씁니다.</p>
          <div className="timestep-row">
            <Field label="Time step 간격">
              <input className="num" inputMode="numeric" value={inc} aria-label="Time step 간격" onChange={(e) => setInc(Math.max(1, Number(e.target.value.replace(/[^0-9]/g, "")) || 1))} />
            </Field>
            <span className="mono small muted" data-testid="steps-preview">
              {timeStepsText(preview.numSteps, inc)}
            </span>
          </div>
          {files && files.length > 0 && (
            <details className="advanced">
              <summary>
                파일 {files.length - excluded.size}/{files.length}
              </summary>
              <div className="filecheck-list">
                {files.map((f) => (
                  <label key={f} className="check small mono">
                    <input
                      type="checkbox"
                      checked={!excluded.has(f)}
                      onChange={(e) => {
                        const n = new Set(excluded);
                        if (e.target.checked) n.delete(f);
                        else n.add(f);
                        setExcluded(n);
                      }}
                    />{" "}
                    {f}
                  </label>
                ))}
              </div>
            </details>
          )}
        </>
      )}
      <FeatureGate feature="curation_h3d">
        {(enabled) => (
          <RunAction
            canExecute={canExec}
            label="큐레이션 실행"
            onRun={submit}
            job={runner.job}
            disabled={!enabled || !preview || !c.source}
            disabledReason={enabled ? "②-1 미리보기가 필요합니다" : undefined}
            error={runner.error}
          />
        )}
      </FeatureGate>
      {latest && <CurationResult cur={latest} datasetLink={`/p/${projectId}/s/${studyId}/stage/3`} />}
    </Card>
  );
}

export function CurationResult({ cur, datasetLink }: { cur: Curation; datasetLink?: string }) {
  if (cur.status === "BUILDING") return <p className="muted small">큐레이션 진행 중…</p>;
  if (cur.status === "FAILED") return <p className="error-text small">큐레이션 실패</p>;
  return (
    <div className="curation-result" data-testid="curation-result">
      <div className="small">
        성공 <b>{cur.ok_count}</b>/{cur.target_count}
        {(cur.failed_count ?? 0) > 0 && <span className="error-text"> · 실패 {(cur.failed_count ?? 0)}</span>}
        {cur.missing_runs.length > 0 && <span className="muted"> · 누락 run {cur.missing_runs.length}</span>}
      </div>
      <CodeLine text={cur.output_display_path} />
      {((cur.failed_count ?? 0) > 0 || cur.missing_runs.length > 0) && (
        <details className="advanced">
          <summary>실패 파일·누락 run</summary>
          <div className="advanced-body grid-gap">
            {(cur.failed_count ?? 0) > 0 && <CurationFileList curationId={cur.id} onlyFailed />}
            {cur.missing_runs.length > 0 && (
              <div className="small">
                <div className="field-label">누락 run (출력 없음)</div>
                <div className="mono wrap-list">{cur.missing_runs.join(", ")}</div>
              </div>
            )}
          </div>
        </details>
      )}
      {cur.kind === "H3D" && (
        <p className="small">
          {cur.used_by_dataset_ids.length ? "③-1 입력으로 사용됨" : "③-1 데이터셋 생성의 기본 입력으로 연결됩니다"}
          {datasetLink && (
            <>
              {" · "}
              <Link to={datasetLink}>③-1로 이동</Link>
            </>
          )}
        </p>
      )}
    </div>
  );
}

export function CurationFileList({ curationId, onlyFailed }: { curationId: string; onlyFailed?: boolean }) {
  const [items, setItems] = useState<CurationFile[] | null>(null);
  useEffect(() => {
    let alive = true;
    api
      .curationFiles(curationId, { ok: onlyFailed ? false : undefined, limit: 200 })
      .then((r) => alive && setItems(r.items))
      .catch(() => alive && setItems([]));
    return () => {
      alive = false;
    };
  }, [curationId, onlyFailed]);
  if (!items) return <span className="muted small">불러오는 중…</span>;
  if (!items.length) return <span className="muted small">없음</span>;
  return (
    <table className="table compact" aria-label="결과 파일 목록">
      <thead>
        <tr>
          <th>run 폴더</th>
          <th>입력</th>
          <th>출력</th>
          <th className="num">종료코드</th>
        </tr>
      </thead>
      <tbody>
        {items.map((f) => (
          <tr key={`${f.run_folder}/${f.input_name}`}>
            <td className="mono small">{f.run_folder}</td>
            <td className="mono small">{f.input_name}</td>
            <td className="mono small">{f.output_name ?? <span className="error-text">없음</span>}</td>
            <td className="num small">{f.exit_code ?? "–"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export { useH3dPreview };
export type { H3dPreview };
