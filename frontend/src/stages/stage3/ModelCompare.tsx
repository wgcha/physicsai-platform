// ③-5 모델 비교 패널(phase3.md §4.3) — 새 API 없음: 선택 수만큼 GET /models/{id}, 서로 다른 데이터셋 수만큼 GET /datasets/{id}.
import { useEffect, useRef, useState } from "react";
import { api, ApiError, errorMessage, type Dataset, type Model } from "../../api";
import { useStudy } from "../../app/StudyContext";
import { distinctDatasetIds, seriesFor } from "./compare";
import { ModelCompareChart } from "./ModelCompareChart";
import { ModelCompareTable, type CompareColumn } from "./ModelCompareTable";

type Entry = { state: "loading" } | { state: "ok"; value: Model } | { state: "missing" } | { state: "error"; message: string };
type DsEntry = { state: "loading" } | { state: "ok"; value: Dataset } | { state: "error" };

/** id별 1회만 조회(StrictMode 이중 effect·선택 변경에도 재요청하지 않음) */
function useCompareData(ids: string[]) {
  const [models, setModels] = useState<Record<string, Entry>>({});
  const [datasets, setDatasets] = useState<Record<string, DsEntry>>({});
  const asked = useRef(new Set<string>());
  const askedDs = useRef(new Set<string>());

  useEffect(() => {
    for (const id of ids) {
      if (asked.current.has(id)) continue;
      asked.current.add(id);
      setModels((s) => ({ ...s, [id]: { state: "loading" } }));
      api
        .model(id)
        .then((value): Entry => ({ state: "ok", value }))
        .catch((e): Entry => (e instanceof ApiError && e.status === 404 ? { state: "missing" } : { state: "error", message: errorMessage(e) }))
        .then((entry) => setModels((s) => ({ ...s, [id]: entry })));
    }
  }, [ids.join("|")]);

  const loaded = ids.map((id) => models[id]).map((e) => (e?.state === "ok" ? e.value : null));
  const dsIds = distinctDatasetIds(loaded);
  useEffect(() => {
    for (const id of dsIds) {
      if (askedDs.current.has(id)) continue;
      askedDs.current.add(id);
      setDatasets((s) => ({ ...s, [id]: { state: "loading" } }));
      api
        .dataset(id)
        .then((value): DsEntry => ({ state: "ok", value }))
        .catch((): DsEntry => ({ state: "error" }))
        .then((entry) => setDatasets((s) => ({ ...s, [id]: entry })));
    }
  }, [dsIds.join("|")]);

  const loading = ids.some((id) => !models[id] || models[id].state === "loading") || dsIds.some((id) => datasets[id]?.state === "loading");
  return { models, datasets, loaded, dsIds, loading };
}

export function ModelCompare({ ids, canExec, onSetFinal, onClose }: { ids: string[]; canExec: boolean; onSetFinal: (id: string) => void; onClose: () => void }) {
  const { study, models: listModels } = useStudy();
  const { models, datasets, loaded, dsIds, loading } = useCompareData(ids);

  const columns: CompareColumn[] = ids.map((id, i) => {
    const e = models[id];
    const list = listModels.find((m) => m.id === id);
    const detail = e?.state === "ok" ? e.value : null;
    // Final·상태는 목록(지정 후 재조회됨) 우선, 수치는 상세
    const model = detail ? { ...detail, status: list?.status ?? detail.status, is_final: study.final_model_id === id } : null;
    const ds = model?.dataset_id ? datasets[model.dataset_id] : undefined;
    return {
      id,
      color: i + 1,
      model,
      fallbackName: list ? `${list.name} v${list.version}` : id,
      problem: e?.state === "missing" ? "모델을 찾을 수 없습니다" : e?.state === "error" ? e.message : null,
      dataset: ds?.state === "ok" ? ds.value : null,
      datasetFailed: ds?.state === "error",
    };
  });

  return (
    <section className="model-compare" aria-label="모델 비교">
      <div className="model-compare-head">
        <span className="field-label">모델 비교 ({ids.length})</span>
        {loading && <span className="muted small">불러오는 중…</span>}
        <button type="button" className="btn small ghost" onClick={onClose}>
          닫기
        </button>
      </div>
      {dsIds.length >= 2 && (
        <div className="warn-box compare-warn" role="note">
          평가 데이터셋이 서로 다릅니다 — 점수를 직접 비교하기 어렵습니다
        </div>
      )}
      <ModelCompareChart series={seriesFor(loaded)} columns={columns} />
      <ModelCompareTable columns={columns} canExec={canExec} onSetFinal={onSetFinal} />
    </section>
  );
}
