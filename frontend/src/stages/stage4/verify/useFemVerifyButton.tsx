// ④·⑤·⑥ 공용 "FEM 검증" 진입(phase3 §21.3.10): 버튼 → `…/stage/4/verify?new=1&…`, 이 출처의 기존 검증이 있으면 회색 링크.
// 해석 연결(fem_verify 기능)이 꺼져 있으면 버튼 비활성 + 문구. 옛 PREDICT_VERIFY 기록의 검증 값 열은 verifyValues로 계속 노출한다.
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { Job } from "../../../api";
import { femVerifyApi, type FemSourceReq, type FemVerifySummary } from "../../../api/femVerify";
import { useStudy } from "../../../app/StudyContext";
import { useFeature } from "../../../components/FeatureGate";
import { useCanExecute } from "../../../hooks/useJobRunner";
import { useLatestJob } from "../../../hooks/useLatestJob";
import { FEM_BUTTON_LABEL, FEM_DISABLED_TEXT, fvLinkText, lookupFilter, matchesSource, sourceToQuery } from "./verifyRules";

/** 안정된 키(출처가 같으면 재조회하지 않음) */
const keyOf = (s: FemSourceReq | null) => (s ? sourceToQuery(s) : "");

export function useFemVerifyButton(source: FemSourceReq | null, hasResult: boolean, legacyPredict?: Job | null) {
  const { study } = useStudy();
  const navigate = useNavigate();
  const canExec = useCanExecute();
  const feature = useFeature("fem_verify");
  const [existing, setExisting] = useState<FemVerifySummary | null>(null);
  const key = keyOf(source);
  const base = `/p/${study.project_id}/s/${study.id}/stage/4/verify`;

  useEffect(() => {
    setExisting(null);
    if (!source || !hasResult) return;
    const filter = lookupFilter(source);
    if (!filter) return;
    let alive = true;
    femVerifyApi
      .list(study.id, { ...filter, limit: 20 })
      .then((r) => alive && setExisting(r.items.find((f) => matchesSource(f, source)) ?? null))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
    // source 객체 대신 key로 비교
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [study.id, key, hasResult]);

  // 옛 PREDICT_VERIFY(PBS 검증 해석) 결과 값 — 새 기록은 없고 옛 기록만 남는다
  const legacy = useLatestJob(study.id, "PREDICT_VERIFY");
  const vjob = legacy.job && legacyPredict && (legacy.job.params as { predict_job_id?: string }).predict_job_id === legacyPredict.id ? legacy.job : null;
  const verifyValues = useMemo(
    () => (vjob?.state === "SUCCEEDED" ? ((vjob.result as { verify_values?: Record<string, number> } | null)?.verify_values ?? null) : null),
    [vjob],
  );

  const disabled = !feature.enabled || !hasResult || !source;
  const button: ReactNode = canExec ? (
    <button
      type="button"
      className="btn"
      disabled={disabled}
      title={!feature.enabled ? FEM_DISABLED_TEXT : !hasResult ? "성공한 예측 결과가 필요합니다" : undefined}
      onClick={() => source && navigate(`${base}?${sourceToQuery(source)}`)}
    >
      {FEM_BUTTON_LABEL}
    </button>
  ) : undefined;

  const notes: ReactNode = (
    <>
      {canExec && !feature.enabled && (
        <p className="muted small fem-note" data-testid="fem-note">
          {FEM_DISABLED_TEXT}
        </p>
      )}
      {existing && (
        <p className="small fem-existing" data-testid="fem-existing">
          <Link className="muted" to={`${base}/${existing.id}`}>
            {fvLinkText(existing)}
          </Link>
        </p>
      )}
    </>
  );

  return { button, notes, verifyValues, canExec, enabled: feature.enabled, existing };
}

/** 표 행용 작은 진입 버튼(기존 검증 조회 없음 — 행마다 목록 API를 부르지 않는다) */
export function FemEntryButton({ source, hasResult }: { source: FemSourceReq; hasResult: boolean }) {
  const { study } = useStudy();
  const navigate = useNavigate();
  const canExec = useCanExecute();
  const feature = useFeature("fem_verify");
  if (!canExec) return null;
  return (
    <button
      type="button"
      className="btn small"
      disabled={!feature.enabled || !hasResult}
      title={!feature.enabled ? FEM_DISABLED_TEXT : undefined}
      onClick={() => navigate(`/p/${study.project_id}/s/${study.id}/stage/4/verify?${sourceToQuery(source)}`)}
    >
      {FEM_BUTTON_LABEL}
    </button>
  );
}
