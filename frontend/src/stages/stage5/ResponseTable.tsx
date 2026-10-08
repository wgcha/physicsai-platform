import { useState } from "react";
import type { OptGoal, OptResponse, ResponseCandidates } from "../../api";

export const GOALS: OptGoal[] = ["NONE", "MINIMIZE", "MAXIMIZE", "CONSTRAINT"];
const STATS: OptResponse["stat"][] = ["MAX", "MIN", "ABSMAX"];
const BOUNDS: NonNullable<OptResponse["bound"]>[] = ["<=", ">=", "=="];
export const NAME_RE = /^[A-Za-z][A-Za-z0-9_]*$/;

/** 원본 GUI:640-647 이름 제안: DataType 대문자화 24자 */
export function suggestName(base: string, taken: string[]): string {
  let n = base.toUpperCase().replace(/[^A-Z0-9_]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 24);
  if (!/^[A-Z]/.test(n)) n = `R_${n}`.slice(0, 24);
  if (!n) n = "RESP";
  let out = n;
  let k = 2;
  const lower = taken.map((t) => t.toLowerCase());
  while (lower.includes(out.toLowerCase())) out = `${n.slice(0, 21)}_${k++}`;
  return out;
}

/** ⑤-2 응답 표: 원본 열 그대로(GUI:100-101). Goal≠CONSTRAINT면 Bound·Value 비활성 */
export function ResponseTable({ rows, onChange, readOnly }: { rows: OptResponse[]; onChange: (rows: OptResponse[]) => void; readOnly: boolean }) {
  const set = (i: number, patch: Partial<OptResponse>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <div className="table-wrap">
      <table className="table compact resp-table" aria-label="응답 표">
        <thead>
          <tr>
            <th>Name</th>
            <th>Source</th>
            <th>Subcase</th>
            <th>DataType/Request</th>
            <th>Component</th>
            <th>Layer</th>
            <th>Stat</th>
            <th>Goal</th>
            <th>Bound</th>
            <th>Value</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td colSpan={11} className="muted small">
                응답이 없습니다. 아래 입력줄에서 추가하세요.
              </td>
            </tr>
          )}
          {rows.map((r, i) => {
            const cons = r.goal === "CONSTRAINT";
            return (
              <tr key={r.name}>
                <td className="mono">{r.name}</td>
                <td>{r.source}</td>
                <td className="num">{r.source === "H3D" ? r.subcase : ""}</td>
                <td>{r.source === "H3D" ? r.datatype : r.request}</td>
                <td>{r.component}</td>
                <td>{r.source === "H3D" ? r.layer : ""}</td>
                <td>{r.stat}</td>
                <td>
                  <select value={r.goal} disabled={readOnly} aria-label={`${r.name} Goal`} onChange={(e) => set(i, { goal: e.target.value as OptGoal })}>
                    {GOALS.map((g) => (
                      <option key={g}>{g}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <select value={r.bound ?? "<="} disabled={readOnly || !cons} aria-label={`${r.name} Bound`} onChange={(e) => set(i, { bound: e.target.value as OptResponse["bound"] })}>
                    {BOUNDS.map((b) => (
                      <option key={b}>{b}</option>
                    ))}
                  </select>
                </td>
                <td>
                  <input
                    className="num-input"
                    aria-label={`${r.name} Value`}
                    disabled={readOnly || !cons}
                    value={r.value === undefined || Number.isNaN(r.value) ? "" : String(r.value)}
                    inputMode="decimal"
                    onChange={(e) => set(i, { value: e.target.value === "" ? undefined : Number(e.target.value) })}
                  />
                </td>
                <td>
                  {!readOnly && (
                    <button type="button" className="icon-btn" aria-label={`${r.name} 삭제`} onClick={() => onChange(rows.filter((_, j) => j !== i))}>
                      ✕
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** 추가 행 입력줄: Source → Subcase → DataType → Component/Layer(후보 API), Stat, Name → 추가. 후보가 없으면 직접 입력(가정 A-10) */
export function ResponseAddRow({ candidates, rows, onAdd }: { candidates: ResponseCandidates | null; rows: OptResponse[]; onAdd: (r: OptResponse) => void }) {
  const [source, setSource] = useState<"H3D" | "XYDATA">("H3D");
  const [subcase, setSubcase] = useState("1");
  const [datatype, setDatatype] = useState("");
  const [request, setRequest] = useState("");
  const [component, setComponent] = useState("");
  const [layer, setLayer] = useState("");
  const [stat, setStat] = useState<OptResponse["stat"]>("MAX");
  const [name, setName] = useState("");
  const [nameTouched, setNameTouched] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const h3d = candidates?.h3d ?? null;
  const xy = candidates?.xydata ?? null;
  const sc = h3d?.subcases.find((s) => String(s.id) === subcase) ?? h3d?.subcases[0];
  const dts = sc?.datatypes ?? [];
  const dtObj = dts.find((d) => d.name === datatype) ?? (h3d ? dts[0] : undefined);
  const dtVal = h3d ? dtObj?.name ?? "" : datatype;
  const comps = source === "H3D" ? dtObj?.components ?? null : xy ? xy.requests[request] ?? Object.values(xy.requests)[0] ?? [] : null;
  const reqVal = xy ? (request in xy.requests ? request : Object.keys(xy.requests)[0] ?? "") : request;
  const compVal = comps ? (comps.includes(component) ? component : comps[0] ?? "") : component;
  const layers = dtObj?.layers ?? null;
  const layerVal = layers ? (layers.includes(layer) ? layer : layers[0] ?? "") : layer;
  const taken = rows.map((r) => r.name);
  const suggested = suggestName(source === "H3D" ? dtVal : reqVal, taken);
  const nameVal = nameTouched ? name : suggested;

  const add = () => {
    setError(null);
    const all = [nameVal, dtVal, reqVal, compVal, layerVal];
    if (all.some((s) => s.includes("|"))) return setError("문자 | 는 쓸 수 없습니다");
    if (!NAME_RE.test(nameVal) || nameVal.length > 64) return setError("Name은 영문자로 시작하는 영문·숫자·_ (64자 이하)");
    if (taken.some((t) => t.toLowerCase() === nameVal.toLowerCase())) return setError("같은 Name이 있습니다");
    if (!compVal.trim()) return setError("Component를 입력하세요");
    if (source === "H3D") {
      const s = Number(subcase);
      if (!Number.isInteger(s) || s < 1) return setError("Subcase는 1 이상 정수");
      if (!dtVal.trim()) return setError("DataType을 입력하세요");
      onAdd({ name: nameVal, source, subcase: s, datatype: dtVal, component: compVal, layer: layerVal, stat, goal: "NONE" });
    } else {
      if (!reqVal.trim()) return setError("Request를 입력하세요");
      onAdd({ name: nameVal, source, request: reqVal, component: compVal, stat, goal: "NONE" });
    }
    setNameTouched(false);
    setName("");
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
        {sel("Source", source, ["H3D", "XYDATA"], (v) => setSource(v as "H3D"))}
        {source === "H3D" ? (
          <>
            {sel("Subcase", subcase, h3d ? h3d.subcases.map((s) => String(s.id)) : null, setSubcase, "narrow")}
            {sel("DataType", dtVal, h3d ? dts.map((d) => d.name) : null, setDatatype)}
            {sel("Component", compVal, comps, setComponent)}
            {sel("Layer", layerVal, layers, setLayer, "narrow")}
          </>
        ) : (
          <>
            {sel("Request", reqVal, xy ? Object.keys(xy.requests) : null, setRequest)}
            {sel("Component", compVal, comps, setComponent)}
          </>
        )}
        {sel("Stat", stat, STATS, (v) => setStat(v as OptResponse["stat"]), "narrow")}
        <input
          aria-label="Name"
          className="mono"
          value={nameVal}
          onChange={(e) => {
            setNameTouched(true);
            setName(e.target.value);
          }}
        />
        <button type="button" className="btn small" onClick={add}>
          추가
        </button>
      </div>
      {!candidates?.h3d && !candidates?.xydata && <p className="muted small">④에서 예측을 한 번 실행하면 목록이 채워집니다. 지금은 직접 입력할 수 있습니다.</p>}
      {error && <p className="error-text small" role="alert">{error}</p>}
    </div>
  );
}
