// ④ 실행 결과 "입력·경로" 카드(phase3 §21.2.3): 파라미터 표 · 모델 · starter · 경로(복사).
import type { PredictRunDetail } from "../../../api/predictRuns";
import { Card, CopyButton } from "../../../components/ui";
import { InputBadge } from "../../../components/InputKindSelect";
import { fmtBytes, fmtNum } from "../../../lib/format";

const PATH_ROWS: { key: keyof PredictRunDetail["paths"]; label: string }[] = [
  { key: "dir", label: "예측 폴더" },
  { key: "input_dir", label: "입력(INPUT)" },
  { key: "result_dir", label: "결과(RESULT)" },
  { key: "pred_h3d", label: "예측 h3d" },
  { key: "media_dir", label: "컨투어 폴더" },
  { key: "geom_dir", label: "형상(geom)" },
];

export function RunInputsCard({ run }: { run: PredictRunDetail }) {
  const names = Object.keys(run.values ?? {});
  const paths = PATH_ROWS.filter((p) => run.paths?.[p.key]);
  const pi = run.predict_input;
  return (
    <Card span="half" title="입력·경로" className="run-inputs">
      <div className="model-line">
        <span className="field-label">모델</span>
        <span>{run.model ? `${run.model.name} v${run.model.version}` : <span className="muted">—</span>}</span>
        {run.starter && (
          <>
            <span className="field-label">starter</span>
            <span className="mono small">{run.starter}</span>
          </>
        )}
        <span className="field-label">입력</span>
        <InputBadge input={run.input} />
        {run.input_mode === "template" && run.template && (
          <>
            <span className="field-label">템플릿</span>
            <span className="small">{run.template.label || run.template.id}</span>
          </>
        )}
      </div>
      {pi && (
        <p className="small" data-testid="predict-input">
          예측 입력 — {pi.starter ? <span className="mono">{pi.starter}</span> : "starter 없음"}
          {pi.files != null && ` · 파일 ${pi.files}개`}
          {pi.bytes != null && ` · ${fmtBytes(pi.bytes)}`}
        </p>
      )}
      {(run.input_warnings ?? []).map((w, i) => (
        <p key={i} className="warn-text small" data-testid="input-warning" title={w.code}>
          {w.message}
        </p>
      ))}
      {run.input_mode === "prepared" && run.input_path && (
        <div className="codeline small" title="준비된 입력 경로">
          <code>{run.input_path}</code>
          <CopyButton text={run.input_path} label="경로 복사" />
        </div>
      )}
      {names.length > 0 && (
        <div className="table-wrap">
          <table className="table compact" aria-label="입력 파라미터">
            <thead>
              <tr>
                <th>파라미터</th>
                <th className="num">입력값</th>
                <th className="num">반영값</th>
                <th>범위 밖</th>
              </tr>
            </thead>
            <tbody>
              {names.map((n) => (
                <tr key={n}>
                  <td className="mono">{n}</td>
                  <td className="num">{fmtNum(run.values[n])}</td>
                  <td className="num">{fmtNum(run.applied_values?.[n] ?? run.values[n])}</td>
                  <td className="small">{run.out_of_range.includes(n) ? <span className="warn-text">범위 밖</span> : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {paths.length > 0 && (
        <div className="run-paths">
          {paths.map((p) => (
            <div key={p.key} className="codeline small" data-testid={`path-${p.key}`}>
              <span className="field-label">{p.label}</span>
              <code>{run.paths[p.key]}</code>
              <CopyButton text={run.paths[p.key]!} label="경로 복사" />
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
