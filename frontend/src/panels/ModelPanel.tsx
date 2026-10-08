import { useState } from "react";
import { api, errorMessage, type Model } from "../api";
import { useStudyOptional } from "../app/StudyContext";
import { fmtNum } from "../lib/format";

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

/** 모델 목록·Final(§16.2 ③) */
export function ModelPanel() {
  const ctx = useStudyOptional();
  const [error, setError] = useState<string | null>(null);
  if (!ctx) return null;
  const { study, models, reloadModels } = ctx;
  const active = models.filter((m) => m.status !== "ARCHIVED");

  const setFinal = async (id: string) => {
    try {
      setError(null);
      await api.setFinalModel(study.id, id);
      await reloadModels();
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  return (
    <section className="panel" aria-label="모델 목록">
      <header className="panel-head">
        <h2>모델</h2>
        <span className="muted small">{active.length}개</span>
      </header>
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
                  <button type="button" className="btn small ghost" onClick={() => setFinal(m.id)}>
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
    </section>
  );
}
