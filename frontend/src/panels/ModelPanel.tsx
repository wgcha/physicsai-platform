import { useState } from "react";
import { api, errorMessage, type Model } from "../api";
import { useStudyOptional, type StudyData } from "../app/StudyContext";
import { CLEANUP_RUNNING_HINT, CLEANUP_RUNNING_TEXT, cleanupRunningMessage, useCleanupRunning } from "../hooks/useCleanupRunning";
import { fmtNum } from "../lib/format";
import { Cell } from "../design/Grid";

export function scoreSummary(m: Model): string {
  if (m.eval_status === "RUNNING") return "평가 중";
  if (m.eval_status === "FAILED") return "평가 실패";
  if (!m.eval_score) return "평가 전";
  if (m.eval_score.status === "UNRECOGNIZED") return "점수 형식 미확인";
  const e = Object.entries(m.eval_score.metrics);
  if (!e.length) return "점수 형식 미확인";
  return e
    .slice(0, 2)
    .map(([k, v]) => `${k} ${fmtNum(v, 3)}`)
    .join(" · ");
}

/** 모델 목록·Final(§16.2 ③) — 레이아웃 A(2026-10-17)부터 ③ 화면 안 카드(우측 고정 열 없음) */
export function ModelPanel() {
  const ctx = useStudyOptional();
  return ctx ? <ModelPanelBody ctx={ctx} /> : null;
}

function ModelPanelBody({ ctx }: { ctx: StudyData }) {
  const [error, setError] = useState<string | null>(null);
  const { study, models, reloadModels } = ctx;
  const cleanup = useCleanupRunning(study.id);
  const active = models.filter((m) => m.status !== "ARCHIVED");

  const setFinal = async (id: string) => {
    try {
      setError(null);
      await api.setFinalModel(study.id, id);
      await reloadModels();
    } catch (e) {
      cleanup.onConflict(e);
      setError(cleanupRunningMessage(e, "Final 모델을 바꿀") ?? errorMessage(e));
    }
  };

  return (
    <Cell span={3} className="panel" label="모델 목록" title={<h2 className="T">모델</h2>} refText={`${active.length}개`}>
      {study.can_execute && cleanup.running && (
        <div className="warn-text small" role="status" data-testid="panel-cleanup-running">
          {CLEANUP_RUNNING_TEXT} — Final 지정은 정리가 끝난 뒤 할 수 있습니다
        </div>
      )}
      {error && <div className="error-text small">{error}</div>}
      {active.length === 0 ? (
        <div className="empty small">등록된 모델이 없습니다(③-4에서 등록)</div>
      ) : (
        <ul className="mlist">
          {active.map((m) => (
            <li key={m.id} className={`mrow ${m.is_final ? "final" : ""}`}>
              <div className="mrow-top">
                <span className="mname">
                  {m.name}
                  <span className="muted"> v{m.version}</span>
                </span>
                {m.is_final ? (
                  <span className="final-badge">Final</span>
                ) : study.can_execute && m.status === "ACTIVE" ? (
                  <button
                    type="button"
                    className="btn small ghost"
                    disabled={cleanup.running}
                    title={cleanup.running ? CLEANUP_RUNNING_HINT : undefined}
                    onClick={() => setFinal(m.id)}
                  >
                    Final로 지정
                  </button>
                ) : null}
              </div>
              <div className="mrow-meta small">
                <span>최종 loss {fmtNum(m.final_loss, 3)}</span>
                <span>최소 {fmtNum(m.min_loss, 3)}</span>
                <span className="muted">{scoreSummary(m)}</span>
                {m.status === "INVALID" && <span className="error-text">무결성 불일치</span>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Cell>
  );
}
