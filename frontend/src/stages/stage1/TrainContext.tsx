import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, errorMessage, type TrainDoe, type TrainRun, type TrainSetup } from "../../api";
import { useStudy } from "../../app/StudyContext";

/** ① 화면 공용 데이터: 학습 설정(파라미터 표·tpl), DOE 목록, 선택한 DOE의 run 목록 */
export interface TrainData {
  setup: TrainSetup | null;
  setupError: string | null;
  does: TrainDoe[];
  doe: TrainDoe | null;
  selectDoe: (id: string) => void;
  runs: TrainRun[];
  reloadSetup: () => Promise<void>;
  reloadDoes: () => Promise<void>;
  reloadRuns: () => Promise<void>;
  setSetup: (s: TrainSetup) => void;
}

const Ctx = createContext<TrainData | null>(null);

export function useTrain(): TrainData {
  const v = useContext(Ctx);
  if (!v) throw new Error("TrainProvider 없음");
  return v;
}

export function TrainProvider({ children }: { children: ReactNode }) {
  const { study } = useStudy();
  const [setup, setSetup] = useState<TrainSetup | null>(null);
  const [setupError, setSetupError] = useState<string | null>(null);
  const [does, setDoes] = useState<TrainDoe[]>([]);
  const [doeId, setDoeId] = useState<string | null>(null);
  const [runs, setRuns] = useState<TrainRun[]>([]);

  const reloadSetup = useCallback(async () => {
    try {
      setSetup(await api.train(study.id));
      setSetupError(null);
    } catch (e) {
      setSetupError(errorMessage(e));
    }
  }, [study.id]);

  const reloadDoes = useCallback(async () => {
    try {
      const list = await api.trainDoes(study.id);
      setDoes(list);
      setDoeId((cur) => (cur && list.some((d) => d.id === cur) ? cur : (list.find((d) => d.status === "READY") ?? list[0])?.id ?? null));
    } catch {
      setDoes([]);
    }
  }, [study.id]);

  const doe = does.find((d) => d.id === doeId) ?? null;

  const reloadRuns = useCallback(async () => {
    if (!doeId) {
      setRuns([]);
      return;
    }
    try {
      const all: TrainRun[] = [];
      let cursor: string | null = null;
      do {
        const page: { items: TrainRun[]; nextCursor: string | null } = await api.trainRuns(doeId, { cursor, limit: 500 });
        all.push(...page.items);
        cursor = page.nextCursor;
      } while (cursor && all.length < 5000);
      setRuns(all);
      setDoes(await api.trainDoes(study.id));
    } catch {
      /* 다음 갱신에서 */
    }
  }, [doeId, study.id]);

  useEffect(() => {
    void reloadSetup();
    void reloadDoes();
  }, [reloadSetup, reloadDoes]);

  useEffect(() => {
    void reloadRuns();
  }, [reloadRuns]);

  return (
    <Ctx.Provider value={{ setup, setupError, does, doe, selectDoe: setDoeId, runs, reloadSetup, reloadDoes, reloadRuns, setSetup }}>
      {children}
    </Ctx.Provider>
  );
}
