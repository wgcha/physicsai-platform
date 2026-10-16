// ④ 템플릿 관리 "응답" 절(phase3.md §14.6): 표(이름·subcase·datatype·component·layer·stat·단위) + "응답 추가" + 행 삭제 + 저장.
// 추가 줄의 목록은 ⑤ response-candidates API(최근 성공 예측의 H3D_PREVIEW.json)를 재사용 — 없으면 회색 안내 + 직접 입력.
import { useEffect, useState } from "react";
import { ApiError, api, errorMessage, type ParamSet, type ResponseCandidates, type ResponseStat, type TemplateResponse } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { NAME_RE, suggestName } from "../stage5/ResponseTable";
import { ComboInput, DEFAULT_RESULT_FIELD } from "./ComboInput";

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
              <th className="num">subcase</th>
              <th>datatype</th>
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
                <td colSpan={canEdit ? 8 : 7} className="muted small">
                  응답 정의가 없습니다{canEdit ? " — 첫 예측 뒤 아래에서 추가하세요" : ""}.
                </td>
              </tr>
            )}
            {rows.map((r, i) => (
              <tr key={r.name}>
                <td className="mono">{r.name}</td>
                <td className="num">{r.spec?.subcase ?? "—"}</td>
                <td>{r.spec?.datatype ?? <span className="muted small">추출 정의 없음</span>}</td>
                <td>{r.spec?.component ?? ""}</td>
                <td>{r.spec?.layer ?? ""}</td>
                <td>{r.spec?.stat ?? ""}</td>
                <td className="small">{r.unit}</td>
                {canEdit && (
                  <td>
                    <button type="button" className="icon-btn" aria-label={`${r.name} 삭제`} onClick={() => setRows(rows.filter((_, j) => j !== i))}>
                      ✕
                    </button>
                  </td>
                )}
              </tr>
            ))}
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
export function ResponseAdd({ candidates, rows, onAdd }: { candidates: ResponseCandidates | null; rows: TemplateResponse[]; onAdd: (r: TemplateResponse) => void }) {
  const h3d = candidates?.h3d ?? null;
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
  const comps = dtObj?.components ?? [];
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

  const add = () => {
    setError(null);
    if ([nameVal, dtVal, compVal, layerVal, unit].some((s) => s.includes("|"))) return setError("문자 | 는 쓸 수 없습니다");
    if (!NAME_RE.test(nameVal) || nameVal.length > 64) return setError("이름은 영문자로 시작하는 영문·숫자·_ (64자 이하)");
    if (taken.some((t) => t.toLowerCase() === nameVal.toLowerCase())) return setError("같은 이름이 있습니다");
    const s = Number(sc ? sc.id : subcase);
    if (!Number.isInteger(s) || s < 1) return setError("subcase는 1 이상 정수");
    if (!dtVal.trim()) return setError("datatype을 입력하세요");
    if (!compVal.trim()) return setError("component를 입력하세요");
    onAdd({ name: nameVal, unit: unit.trim(), spec: { source: "H3D", subcase: s, datatype: dtVal, component: compVal, layer: layerVal, stat } });
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
        {sel("subcase", sc ? String(sc.id) : subcase, h3d ? h3d.subcases.map((x) => String(x.id)) : null, setSubcase, "narrow")}
        <ComboInput id="resp-add-dt" label="datatype" value={dtVal} options={dts.map((d) => d.name)} onChange={onDatatype} placeholder={DEFAULT_RESULT_FIELD} />
        <ComboInput id="resp-add-comp" label="component" value={compVal} options={comps} onChange={setComponent} placeholder="component" />
        {sel("layer", layerVal, layers, setLayer, "narrow")}
        {sel("stat", stat, STATS, (v) => setStat(v as ResponseStat), "narrow")}
        <input aria-label="단위" className="narrow" value={unit} placeholder="단위" onChange={(e) => setUnit(e.target.value)} />
        <input
          aria-label="응답 이름"
          className="mono"
          value={nameVal}
          onChange={(e) => {
            setNameTouched(true);
            setName(e.target.value);
          }}
        />
        <button type="button" className="btn small" onClick={add}>
          응답 추가
        </button>
      </div>
      {!dts.length && (
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
