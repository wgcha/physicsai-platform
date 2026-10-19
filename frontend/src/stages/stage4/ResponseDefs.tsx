// ④ 템플릿 관리 "응답" 절(phase3.md §14.6, S17 §22.3): 표(이름·출처·subcase·datatype(커브면 계열)·component·layer·stat·단위) + "응답 추가"(출처 H3D·커브) + 행 삭제 + 저장.
// 추가 줄의 목록은 ⑤ response-candidates API(최근 성공 예측의 H3D_PREVIEW.json·xydata)를 재사용 — 없으면 회색 안내 + 직접 입력.
import { useEffect, useState } from "react";
import { ApiError, api, errorMessage, type ParamSet, type ResponseCandidates, type ResponseStat, type TemplateResponse } from "../../api";
import { specCells, SRC_LABEL } from "../stage5/surrogate/perfRules";
import { useStudy } from "../../app/StudyContext";
import { NAME_RE, suggestName } from "../stage5/ResponseTable";
import { ComboInput, DEFAULT_RESULT_COMPONENT, DEFAULT_RESULT_FIELD, componentOptions } from "./ComboInput";

const STATS: ResponseStat[] = ["MAX", "MIN", "ABSMAX"];
export const NO_CANDIDATES_TEXT = "예측을 한 번 실행하면 목록이 채워집니다";
/** D3-53: datatype 후보가 없을 때 */
export const TYPE_HINT_TEXT = `예측 결과 목록이 없으면 직접 입력하세요(예: ${DEFAULT_RESULT_FIELD})`;

export function ResponseDefs({ ps, canEdit }: { ps: ParamSet; canEdit: boolean }) {
  const { study, reloadParamSets } = useStudy();
  const [rows, setRows] = useState<TemplateResponse[]>(ps.responses);
  const [cands, setCands] = useState<ResponseCandidates | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);
  useEffect(() => setRows(ps.responses), [ps]);
  useEffect(() => {
    if (!canEdit) return;
    api.responseCandidates(study.id).then(setCands).catch(() => setCands(null));
  }, [study.id, canEdit]);

  const dirty = JSON.stringify(rows) !== JSON.stringify(ps.responses);
  const save = async () => {
    setBusy(true);
    setError(null);
    setProblems([]);
    setSaved(false);
    try {
      await api.putParamSetResponses(ps.id, { responses: rows.map((r) => ({ name: r.name, unit: r.unit, spec: r.spec ?? null })) });
      await reloadParamSets();
      setSaved(true);
    } catch (e) {
      setError(errorMessage(e));
      const p = e instanceof ApiError ? (e.detail.problems as { message: string }[] | undefined) : undefined;
      setProblems((p ?? []).map((x) => x.message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="resp-defs" data-testid="resp-defs">
      <div className="field-label">응답</div>
      <div className="table-wrap">
        <table className="table compact" aria-label="응답 정의">
          <thead>
            <tr>
              <th>이름</th>
              <th>출처</th>
              <th className="num">subcase</th>
              <th>datatype · 커브 계열</th>
              <th>component</th>
              <th>layer</th>
              <th>stat</th>
              <th>단위</th>
              {canEdit && <th />}
            </tr>
          </thead>
          <tbody>
            {!rows.length && (
              <tr>
                <td colSpan={canEdit ? 9 : 8} className="muted small">
                  응답 정의가 없습니다{canEdit ? " — 첫 예측 뒤 아래에서 추가하세요" : ""}.
                </td>
              </tr>
            )}
            {rows.map((r, i) => {
              const c = r.spec ? specCells(r.spec) : null;
              return (
              <tr key={r.name}>
                <td className="mono">{r.name}</td>
                <td className="small">{r.spec ? SRC_LABEL[r.spec.source] ?? r.spec.source : ""}</td>
                <td className="num">{c?.subcase || "—"}</td>
                <td>{c ? c.datatype : <span className="muted small">추출 정의 없음</span>}</td>
                <td>{c?.component ?? ""}</td>
                <td>{c?.layer ?? ""}</td>
                <td>{c?.stat ?? ""}</td>
                <td className="small">{r.unit}</td>
                {canEdit && (
                  <td>
                    <button type="button" className="icon-btn" aria-label={`${r.name} 삭제`} onClick={() => setRows(rows.filter((_, j) => j !== i))}>
                      ✕
                    </button>
                  </td>
                )}
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {canEdit && (
        <>
          <ResponseAdd candidates={cands} rows={rows} onAdd={(r) => setRows([...rows, r])} />
          <div className="run-action-row">
            <button type="button" className="btn" disabled={!dirty || busy} onClick={save}>
              {busy ? "저장 중…" : "응답 저장"}
            </button>
            {saved && !dirty && <span className="muted small">저장했습니다</span>}
            {error && (
              <span className="error-text small" role="alert">
                {error}
              </span>
            )}
          </div>
          {problems.length > 0 && (
            <ul className="problems small">
              {problems.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

/** "응답 추가" 줄: subcase → datatype → component·layer(후보 목록에서 고르기), stat, 단위, 이름 */
/** S17 §22.12 커브 계열 후보: xydata 요청(request / component) + 최근 예측의 계열(extra) */
export function curveSeriesOptions(candidates: ResponseCandidates | null, extra: string[] = []): string[] {
  const out = [...extra];
  for (const [req, comps] of Object.entries(candidates?.xydata?.requests ?? {})) {
    for (const c of comps.length ? comps : [""]) {
      const s = c ? `${req} / ${c}` : req;
      if (!out.includes(s)) out.push(s);
    }
  }
  return out;
}

export function ResponseAdd({ candidates, rows, onAdd, seriesHints = [] }: { candidates: ResponseCandidates | null; rows: TemplateResponse[]; onAdd: (r: TemplateResponse) => void; seriesHints?: string[] }) {
  const h3d = candidates?.h3d ?? null;
  const [src, setSrc] = useState<"H3D" | "CURVE">("H3D");
  const [series, setSeries] = useState("");
  const [subcase, setSubcase] = useState("1");
  const [datatype, setDatatype] = useState("");
  const [component, setComponent] = useState("");
  const [layer, setLayer] = useState("");
  const [stat, setStat] = useState<ResponseStat>("MAX");
  const [unit, setUnit] = useState("");
  const [name, setName] = useState("");
  const [nameTouched, setNameTouched] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sc = h3d?.subcases.find((s) => String(s.id) === subcase) ?? h3d?.subcases[0];
  const dts = sc?.datatypes ?? [];
  // D3-53: datatype·component는 목록에 없어도 직접 입력(입력란 + datalist). 후보가 오면 빈 칸만 첫 후보로 채운다
  useEffect(() => {
    if (!datatype && dts.length) {
      setDatatype(dts[0].name);
      if (!component) setComponent(dts[0].components[0] ?? "");
    }
  }, [h3d]);
  const dtObj = dts.find((d) => d.name === datatype);
  const dtVal = datatype;
  // D3-54: component는 선택(비우면 요청 줄의 빈 필드). datatype이 CornerStress면 후보에 vonMises
  const comps = componentOptions(dtVal, dtObj?.components ?? []);
  const compHint = dtVal.trim() === DEFAULT_RESULT_FIELD ? `없음(예: ${DEFAULT_RESULT_COMPONENT})` : "없음";
  const compVal = component;
  const onDatatype = (v: string) => {
    setDatatype(v);
    const d = dts.find((x) => x.name === v);
    if (d && !d.components.includes(component)) setComponent(d.components[0] ?? "");
  };
  const layers = h3d && dtObj ? (dtObj.layers.length ? dtObj.layers : [""]) : null;
  const layerVal = layers ? (layers.includes(layer) ? layer : layers[0] ?? "") : layer;
  const taken = rows.map((r) => r.name);
  const nameVal = nameTouched ? name : suggestName(dtVal || "RESP", taken);

  const seriesOpts = curveSeriesOptions(candidates, seriesHints);
  const curveName = nameTouched ? name : suggestName(series.trim() ? series.replace(/[^A-Za-z0-9]+/g, "_") || "CURVE" : "CURVE", taken);
  const addCurve = () => {
    setError(null);
    const sName = series.trim();
    if ([curveName, sName, unit].some((s) => s.includes("|"))) return setError("문자 | 는 쓸 수 없습니다");
    if ([...sName].some((ch) => ch.charCodeAt(0) < 32)) return setError("계열 이름에 제어 문자는 쓸 수 없습니다");
    if (sName.length > 200) return setError("계열 이름은 200자 이하");
    if (!NAME_RE.test(curveName) || curveName.length > 64) return setError("이름은 영문자로 시작하는 영문·숫자·_ (64자 이하)");
    if (taken.some((t) => t.toLowerCase() === curveName.toLowerCase())) return setError("같은 이름이 있습니다");
    onAdd({ name: curveName, unit: unit.trim(), spec: { source: "CURVE", series: sName === "" ? null : sName, stat } });
    setNameTouched(false);
    setName("");
    setUnit("");
    setSeries("");
  };
  const add = () => {
    setError(null);
    if ([nameVal, dtVal, compVal, layerVal, unit].some((s) => s.includes("|"))) return setError("문자 | 는 쓸 수 없습니다");
    if (!NAME_RE.test(nameVal) || nameVal.length > 64) return setError("이름은 영문자로 시작하는 영문·숫자·_ (64자 이하)");
    if (taken.some((t) => t.toLowerCase() === nameVal.toLowerCase())) return setError("같은 이름이 있습니다");
    const s = Number(sc ? sc.id : subcase);
    if (!Number.isInteger(s) || s < 1) return setError("subcase는 1 이상 정수");
    if (!dtVal.trim()) return setError("datatype을 입력하세요");
    onAdd({ name: nameVal, unit: unit.trim(), spec: { source: "H3D", subcase: s, datatype: dtVal, component: compVal.trim(), layer: layerVal, stat } });
    setNameTouched(false);
    setName("");
    setUnit("");
  };

  const sel = (label: string, value: string, opts: string[] | null, onChange: (v: string) => void, className = "") =>
    opts ? (
      <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} className={className}>
        {opts.map((o) => (
          <option key={o} value={o}>
            {o === "" ? "(없음)" : o}
          </option>
        ))}
      </select>
    ) : (
      <input aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} className={className} placeholder={label} />
    );

  return (
    <div className="resp-add">
      <div className="resp-add-row" role="group" aria-label="응답 추가">
        <select aria-label="출처" className="narrow" value={src} onChange={(e) => setSrc(e.target.value as "H3D" | "CURVE")}>
          <option value="H3D">H3D</option>
          <option value="CURVE">커브</option>
        </select>
        {src === "H3D" ? (
          <>
            {sel("subcase", sc ? String(sc.id) : subcase, h3d ? h3d.subcases.map((x) => String(x.id)) : null, setSubcase, "narrow")}
            <ComboInput id="resp-add-dt" label="datatype" value={dtVal} options={dts.map((d) => d.name)} onChange={onDatatype} placeholder={DEFAULT_RESULT_FIELD} />
            <ComboInput id="resp-add-comp" label="component" value={compVal} options={comps} onChange={setComponent} placeholder={compHint} />
            {sel("layer", layerVal, layers, setLayer, "narrow")}
          </>
        ) : (
          <ComboInput id="resp-add-series" label="커브 계열" value={series} options={seriesOpts} onChange={setSeries} placeholder="비우면 첫 계열" />
        )}
        {sel("stat", stat, STATS, (v) => setStat(v as ResponseStat), "narrow")}
        <input aria-label="단위" className="narrow" value={unit} placeholder="단위" onChange={(e) => setUnit(e.target.value)} />
        <input
          aria-label="응답 이름"
          className="mono"
          value={src === "H3D" ? nameVal : curveName}
          onChange={(e) => {
            setNameTouched(true);
            setName(e.target.value);
          }}
        />
        <button type="button" className="btn small" onClick={src === "H3D" ? add : addCurve}>
          응답 추가
        </button>
      </div>
      {src === "CURVE" && <p className="muted small" data-testid="curve-hint">커브 성능은 예측 run의 curve.json 계열 1개의 대표값(최대·최소·|최대|)입니다.</p>}
      {src === "H3D" && !dts.length && (
        <p className="muted small" data-testid="no-candidates">
          {NO_CANDIDATES_TEXT} — {TYPE_HINT_TEXT}.
        </p>
      )}
      {error && (
        <p className="error-text small" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
