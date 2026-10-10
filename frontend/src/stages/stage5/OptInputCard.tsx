import { useStudy } from "../../app/StudyContext";
import { Advanced, Card } from "../../components/ui";

// ---------------------------------------------------------------- ⑤-1
export function OptInputCard({ modelId, setModelId }: { modelId: string; setModelId: (v: string) => void }) {
  const { currentParamSet: ps, models } = useStudy();
  const active = models.filter((m) => m.status === "ACTIVE");
  const final = active.find((m) => m.is_final);
  const chosen = active.find((m) => m.id === modelId) ?? final;
  return (
    <Card step="⑤-1" title="입력">
      {ps ? (
        <div className="ps-summary small">
          <span>
            파라미터 세트 · 파라미터 <b>{ps.parameters.length}</b>
          </span>
          <span>
            학습 샘플 <b>{ps.sample_count}</b>
          </span>
          <span>단위계 {ps.unit_system}</span>
          <span className="mono muted ellipsis" title={ps.source_path}>
            {ps.source_path}
          </span>
        </div>
      ) : (
        <p className="muted">파라미터 세트가 없습니다 — ④에서 먼저 등록하세요.</p>
      )}
      <div className="model-line">
        <span className="field-label">모델</span>
        {chosen ? (
          <span>
            <b>{chosen.name}</b> v{chosen.version} {chosen.is_final && <span className="final-badge">Final</span>}
          </span>
        ) : (
          <span className="muted">Final 모델을 먼저 지정하세요</span>
        )}
      </div>
      <Advanced label="다른 모델">
        <select value={modelId} onChange={(e) => setModelId(e.target.value)} aria-label="모델 선택">
          <option value="">Final 모델(기본)</option>
          {active.map((m) => (
            <option key={m.id} value={m.id}>
              {m.name} v{m.version}
            </option>
          ))}
        </select>
      </Advanced>
    </Card>
  );
}
