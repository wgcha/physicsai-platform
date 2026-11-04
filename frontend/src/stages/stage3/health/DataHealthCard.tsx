import { Fragment, useState } from "react";
import { api, errorMessage, type DataHealthReport, type DhRun } from "../../../api";
import { Card } from "../../../components/ui";
import { ConfirmDialog } from "../../../components/ConfirmDialog";
import { saveBlob } from "../../../lib/download";
import {
  CONFIRM_KEEP, WARN_TIP, clearSelection, fmtVal, fmtZ, fmtCons, fmtSound, framesUnknown, hasSigma, keptRequired, maxRobust, naHeavy, reasonCell, refText, thresholdText,
  selectRecommended, sigmaOnly, termText, toggle, visibleRuns,
} from "./healthModel";

/** ③-1 아래 전폭 카드: 이상치 제외 추천 표(data-health.md §9). 표는 최대 높이 안에서만 스크롤 */
export function DataHealthCard({ report, jobId, selected, onSelect }: {
  report: DataHealthReport;
  jobId: string;
  selected: Set<string>;
  onSelect: (s: Set<string>) => void;
}) {
  const s = report.summary;
  const [onlyRec, setOnlyRec] = useState(true);
  const [open, setOpen] = useState<string | null>(null);
  const [ask, setAsk] = useState<string | null>(null);
  const [csvErr, setCsvErr] = useState<string | null>(null);
  const rows = visibleRuns(report.runs, onlyRec, selected);
  const metricLabel = new Map(report.metrics.map((m) => [m.id, m.label]));
  const label = (id: string) => metricLabel.get(id) ?? id;
  const kept = new Set(keptRequired(report.runs, selected));
  const ref = refText(s);
  const heavy = naHeavy(report);
  const th = thresholdText(s.thresholds);

  const onCheck = (r: DhRun, on: boolean) => {
    if (!on && r.required) setAsk(r.file_rel);
    else onSelect(toggle(selected, r.file_rel, on));
  };
  const csv = async () => {
    setCsvErr(null);
    try {
      const a = (await api.artifacts(jobId)).find((x) => x.kind === "DATA_HEALTH_CSV");
      if (!a) throw new Error("CSV 산출물이 없습니다");
      saveBlob(await api.artifactBlob(a.id), a.file_name);
    } catch (e) {
      setCsvErr(errorMessage(e));
    }
  };

  return (
    <Card
      span={12}
      step="③-1"
      title="데이터 점검 — 이상치 제외 추천"
      foot={
        <div className="dh-foot">
          <button type="button" className="btn small" onClick={() => onSelect(selectRecommended(selected, report.runs))}>추천 항목 선택</button>
          <button type="button" className="btn small ghost" onClick={() => onSelect(clearSelection(selected, report.runs))}>선택 해제</button>
          <button type="button" className="btn small ghost" onClick={() => void csv()}>CSV 내려받기</button>
          {csvErr && <span className="error-text small" role="alert">{csvErr}</span>}
          <span className="dh-count" data-testid="dh-count">제외 {selected.size}개 — 데이터셋 생성에 반영</span>
        </div>
      }
    >
      <div className="dh-head" data-testid="dh-head">
        <span>run <b>{s.n_runs}</b></span>
        <span>추천 <b>{s.n_recommended}</b></span>
        <span>제외 필수 <b>{s.n_required}</b></span>
        <span>3σ만 <b>{s.n_sigma_only}</b></span>
        <span>건전성 FAIL <b>{s.n_sound_fail}</b></span>
        {heavy.length > 0 && <span className="muted">NA 많음: {heavy.join(", ")}</span>}
        <span className="muted" title={th.tip}>{th.text}</span>
        {ref && <span data-testid="dh-ref">{ref}</span>}
        {s.n_frames_unknown > 0 && (
          <span className="pill warn" data-testid="dh-frames-unknown" title="hw 불가 또는 조회 실패 — 이 run들은 프레임 일관성을 검사하지 못함">
            프레임 확인 불가 {s.n_frames_unknown}건
          </span>
        )}
        {(s.n_consistency_undecided ?? 0) > 0 && (
          <span className="pill warn" data-testid="dh-undecided" title="기준값(프레임·종료 시각)이 정해지지 않아 일관성을 판정하지 못한 run">
            일관성 판정 불가 {s.n_consistency_undecided}건
          </span>
        )}
        {s.warnings.map((w) => (
          <span key={w.code} className="pill warn" title={`${w.code}\n${WARN_TIP[w.code] ?? w.message}`}>{WARN_TIP[w.code] ?? w.message}</span>
        ))}
        {report.truncated && <span className="pill warn" data-testid="dh-truncated" title="크기 상한으로 점수 상위 행만 남김">표시 상한 초과 — 상위 {report.runs.length}개만 표시</span>}
        <label className="check dh-filter">
          <input type="checkbox" checked={onlyRec} onChange={(e) => setOnlyRec(e.target.checked)} /> 추천만
        </label>
      </div>
      <div className="dh-scroll" data-testid="dh-scroll">
        <table className="table compact" aria-label="데이터 점검 표">
          <thead>
            <tr>
              <th>선택</th>
              <th>run</th>
              <th>추천</th>
              <th className="num">점수</th>
              <th>사유</th>
              <th>종료</th>
              <th className="num">프레임 (값 / 기준)</th>
              <th className="num">마지막 시각 (값 / 기준)</th>
              <th className="num">에너지 오차% (값 / 기준)</th>
              <th className="num">추가 질량 (값 / 기준)</th>
              <th>최대 견고 z (지표)</th>
              <th>3σ</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={12} className="muted">표시할 run이 없습니다 — 추천 항목이 없습니다.</td></tr>
            )}
            {rows.map((r) => {
              const rc = reasonCell(r.reasons);
              const mr = maxRobust(r);
              const isOpen = open === r.file_rel;
              return (
                <Fragment key={r.file_rel}>
                  <tr className={`${r.required ? "dh-required" : r.recommended ? "dh-rec" : ""}`} data-testid={`dh-row-${r.file_rel}`}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`제외 ${r.file_rel}`}
                        checked={selected.has(r.file_rel)}
                        onChange={(e) => onCheck(r, e.target.checked)}
                      />
                      {kept.has(r.file_rel) && <span className="warn-text" title="제외 필수 run을 포함합니다" aria-label="경고">⚠</span>}
                    </td>
                    <td>
                      <button type="button" className="btn small ghost dh-exp" aria-expanded={isOpen} aria-label={`지표 ${isOpen ? "접기" : "펼치기"} ${r.file_rel}`} onClick={() => setOpen(isOpen ? null : r.file_rel)}>
                        {isOpen ? "▾" : "▸"}
                      </button>
                      <span className="mono small" title={r.file_rel}>{r.file_rel}</span>
                      {r.run_key && <span className="muted small"> · {r.run_key}</span>}
                    </td>
                    <td>
                      {r.required ? <span className="pill bad">제외 필수</span> : r.recommended ? <span className="pill warn">추천</span> : <span className="muted">–</span>}
                    </td>
                    <td className="num">{r.score.toFixed(1)}</td>
                    <td className="small" title={rc.tip}>{rc.text || "–"}</td>
                    <td className="small">{termText(r.sound.term)}</td>
                    <td className="num" title={r.consistency.frames?.code ?? undefined}>{framesUnknown(r) ? <span className="muted">확인 불가</span> : fmtCons(r.consistency.frames)}</td>
                    <td className="num" title={r.consistency.t_last?.code ?? undefined}>{fmtCons(r.consistency.t_last)}</td>
                    <td className="num">{fmtSound(r.sound.energy_err_pct)}</td>
                    <td className="num">{fmtSound(r.sound.added_mass)}</td>
                    <td className="small">{mr ? `${fmtZ(mr.zr)} (${label(mr.id)})` : "–"}</td>
                    <td>{sigmaOnly(r) ? <span className="pill" title="일반 3σ만 넘음 — 견고 기준으로는 추천 아님">3σ만</span> : hasSigma(r, s.thresholds.sigma_z ?? 3) ? <span className="pill">3σ</span> : ""}</td>
                  </tr>
                  {isOpen && (
                    <tr className="dh-detail">
                      <td colSpan={12}>
                        <table className="table compact" aria-label={`지표 ${r.file_rel}`}>
                          <thead>
                            <tr><th>지표</th><th className="num">값</th><th className="num">z</th><th className="num">견고 z</th><th className="num">kNN 점수</th><th className="num">이웃 거리</th><th>비고</th></tr>
                          </thead>
                          <tbody>
                            {Object.entries(r.values).map(([id, v]) => (
                              <tr key={id} className={v.fail ? "dh-fail" : undefined}>
                                <td>{label(id)}</td>
                                <td className="num">{fmtVal(v)}</td>
                                <td className="num">{fmtZ(v.z)}</td>
                                <td className="num">{fmtZ(v.zr)}</td>
                                <td className="num">{fmtZ(v.s)}</td>
                                <td className="num">{v.knn_dist != null ? v.knn_dist.toFixed(3) : "–"}</td>
                                <td className="small muted" title={v.na ?? undefined}>{v.na ? `NA(${v.na})` : ""}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      {ask && (
        <ConfirmDialog
          title="제외 필수 run 포함"
          body={CONFIRM_KEEP}
          confirmLabel="포함"
          danger
          onConfirm={() => {
            onSelect(toggle(selected, ask, false));
            setAsk(null);
          }}
          onCancel={() => setAsk(null)}
        />
      )}
    </Card>
  );
}
