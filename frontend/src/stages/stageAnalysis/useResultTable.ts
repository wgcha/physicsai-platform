// ⑤ 결과 표 불러오기(phase3.md §19.4): 출처 (a) 일괄 예측 배치 = 기존 GET /predict-batches/{bid}(진행 중이면 POLL.batch로 갱신) + GET …/design-map(완료 수·상태가 바뀔 때만),
// 출처 (b) 해석 DOE = GET /train-does/{id}/result-table(doeKey = sample_status·status가 바뀔 때만 다시). 둘 다 같은 ResultTable로 변환(adapters).
import { useCallback, useEffect, useMemo, useState } from "react";
import { api, errorMessage, type PredictBatch } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { analysisApi, type DoeResultTable } from "../../api/analysis";
import { designMapApi, type DesignMap } from "../../api/designMap";
import { fromBatch } from "../../analysis/adapters/fromBatch";
import { fromDoe } from "../../analysis/adapters/fromDoe";
import type { ResultTable } from "../../analysis/resultTable";
import { usePolling } from "../../hooks/usePolling";
import { POLL } from "../../lib/poll";
import { isBatchActive } from "../stage4/batch/batchTable";

export type SourceKind = "batch" | "doe";

export interface Loaded {
  table: ResultTable | null;
  error: string | null;
  loading: boolean;
}

export function useResultTable(kind: SourceKind | null, id: string | null, doeKey = ""): Loaded {
  const [b, setB] = useState<PredictBatch | null>(null);
  const [dm, setDm] = useState<{ id: string; v: string; map: DesignMap | null } | null>(null);
  const [doe, setDoe] = useState<DoeResultTable | null>(null);
  const [error, setError] = useState<{ id: string; msg: string } | null>(null);
  const { paramSets } = useStudy();

  const batchId = kind === "batch" ? id : null;
  const doeId = kind === "doe" ? id : null;

  const loadBatch = useCallback(async () => {
    if (!batchId) return;
    try {
      setB(await api.batch(batchId));
      setError(null);
    } catch (e) {
      setError({ id: batchId, msg: errorMessage(e) });
    }
  }, [batchId]);
  useEffect(() => {
    void loadBatch();
  }, [loadBatch]);
  usePolling(loadBatch, b && b.id === batchId && isBatchActive(b.status) ? POLL.batch : null, false, [batchId]);

  const dmVersion = b && b.id === batchId ? `${b.predict.succeeded}|${b.status}` : null;
  useEffect(() => {
    if (!batchId || dmVersion === null) return;
    let alive = true;
    designMapApi
      .get(batchId)
      .then((map) => alive && setDm({ id: batchId, v: dmVersion, map }))
      .catch(() => alive && setDm({ id: batchId, v: dmVersion, map: null }));
    return () => {
      alive = false;
    };
  }, [batchId, dmVersion]);

  useEffect(() => {
    if (!doeId) return;
    let alive = true;
    analysisApi
      .doeResultTable(doeId)
      .then((t) => alive && (setDoe(t), setError(null)))
      .catch((e) => alive && setError({ id: doeId, msg: errorMessage(e) }));
    return () => {
      alive = false;
    };
  }, [doeId, doeKey]);

  const table = useMemo(() => {
    if (batchId && b && b.id === batchId && dm && dm.id === batchId) return fromBatch(b, dm.map, undefined, paramSets.find((p) => p.id === (b as { param_set?: { id?: string } }).param_set?.id)?.responses ?? null);
    if (doeId && doe && doe.doe_id === doeId) return fromDoe(doe);
    return null;
  }, [batchId, doeId, b, dm, doe, paramSets]);
  const err = error && error.id === id ? error.msg : null;
  return { table: err ? null : table, error: err, loading: !!id && !table && !err };
}
