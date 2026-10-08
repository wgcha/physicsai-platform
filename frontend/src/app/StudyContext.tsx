import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type Dataset, type Model, type ParamSet, type Study } from "../api";

export interface StudyData {
  study: Study;
  datasets: Dataset[];
  models: Model[];
  paramSets: ParamSet[];
  currentParamSet: ParamSet | null;
  reloadStudy: () => Promise<void>;
  reloadDatasets: () => Promise<void>;
  reloadModels: () => Promise<void>;
  reloadParamSets: () => Promise<void>;
}

const Ctx = createContext<StudyData | null>(null);

export function useStudy(): StudyData {
  const v = useContext(Ctx);
  if (!v) throw new Error("StudyProvider 없음");
  return v;
}

export function useStudyOptional(): StudyData | null {
  return useContext(Ctx);
}

export function StudyProvider({ studyId, children }: { studyId: string; children: ReactNode }) {
  const [study, setStudy] = useState<Study | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [paramSets, setParamSets] = useState<ParamSet[]>([]);
  const [error, setError] = useState<string | null>(null);

  const reloadStudy = useCallback(async () => setStudy(await api.study(studyId)), [studyId]);
  const reloadDatasets = useCallback(async () => setDatasets(await api.datasets(studyId)), [studyId]);
  const reloadModels = useCallback(async () => {
    setModels(await api.models(studyId));
    setStudy(await api.study(studyId));
  }, [studyId]);
  const reloadParamSets = useCallback(async () => setParamSets(await api.paramSets(studyId)), [studyId]);

  useEffect(() => {
    setStudy(null);
    setError(null);
    Promise.all([api.study(studyId), api.datasets(studyId), api.models(studyId), api.paramSets(studyId)])
      .then(([s, d, m, p]) => {
        setStudy(s);
        setDatasets(d);
        setModels(m);
        setParamSets(p);
      })
      .catch((e) => setError(e?.message ?? String(e)));
  }, [studyId]);

  if (error) return <div className="empty">Study를 불러오지 못했습니다: {error}</div>;
  if (!study) return <div className="empty">불러오는 중…</div>;
  const currentParamSet = paramSets.find((p) => p.is_current) ?? null;
  return (
    <Ctx.Provider
      value={{ study, datasets, models, paramSets, currentParamSet, reloadStudy, reloadDatasets, reloadModels, reloadParamSets }}
    >
      {children}
    </Ctx.Provider>
  );
}
