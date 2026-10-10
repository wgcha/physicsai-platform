import { useMemo, useState } from "react";
import { useCanExecute, useJobRunner } from "../../hooks/useJobRunner";
import { Advanced, Card, Field, RunAction } from "../../components/ui";
import { FeatureGate } from "../../components/FeatureGate";
import { parseH3dPreview } from "../../lib/curation";
import { sameSource, useCuration } from "./CurationContext";
import { useJobJson } from "./Sources";

/** 최근 h3d 미리보기 작업 + 지금 원천과 일치할 때만 결과 */
export function useH3dPreview() {
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

