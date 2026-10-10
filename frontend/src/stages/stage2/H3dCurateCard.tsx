import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { type Curation } from "../../api";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Card, Field, RunAction } from "../../components/ui";
import { FeatureGate } from "../../components/FeatureGate";
import { timeStepsText } from "../../lib/curation";
import { useCuration } from "./CurationContext";
import { CurationResult } from "./CurationResult";
import { useH3dPreview } from "./H3dPreviewCard";

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
