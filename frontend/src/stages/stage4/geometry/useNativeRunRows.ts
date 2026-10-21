// ⑥ 내장 최적화·④ 일괄 예측 공용(native-vars.md §7.2·§7.3): Native 템플릿의 세트 정의로 표 행을 초기화하고, 풀·학습 범위를 불러온다.
// 편집(추가·제외·범위)은 이 실행에만 적용 — 세트 정의는 안 바뀐다(D4). 모델을 바꾸면 학습 범위만 갱신하고 편집은 유지한다.
// 다중 baseline 등 editable=false이면 rows = null(기존 표 그대로).
import { useEffect, useRef, useState } from "react";
import { api, type NativeVars, type ParamSet } from "../../../api";
import { NO_EDIT, propRows, runRows, type NativeRow } from "../../../lib/nativeVars";

export interface NativeRunRows {
  native: boolean;
  /** Native인데 아직 불러오는 중(기존 표를 잠깐 보이지 않게) */
  pending: boolean;
  nv: NativeVars | null;
  rows: NativeRow[] | null;
  setRows: (fn: (rs: NativeRow[]) => NativeRow[]) => void;
}

export function useNativeRunRows(ps: ParamSet | null, modelId: string | null): NativeRunRows {
  const native = ps?.engine === "native";
  const [nv, setNv] = useState<NativeVars | null>(null);
  const [rows, setRowsState] = useState<NativeRow[] | null>(null);
  const [failed, setFailed] = useState(false);
  const owner = useRef<string | null>(null);
  const key = ps?.id ?? null;
  const rev = ps?.native?.vars_revision ?? 0;
  useEffect(() => {
    setNv(null);
    setRowsState(null);
    setFailed(false);
    owner.current = null;
  }, [key, rev]);
  useEffect(() => {
    if (!ps || !native) return;
    let alive = true;
    api
      .nativeVars(ps.id, { model_id: modelId })
      .then((d) => {
        if (!alive) return;
        setNv(d);
        setRowsState((prev) => {
          if (!d.editable) return null;
          if (!prev || owner.current !== ps.id) {
            owner.current = ps.id;
            return runRows(d, NO_EDIT, propRows(ps));
          }
          const pool = new Map(d.pool.map((p) => [p.name, p]));
          return prev.map((r) => {
            const p = pool.get(r.name);
            return p ? { ...r, train: p.train ?? null } : r;
          });
        });
      })
      .catch(() => alive && (setNv(null), setFailed(true)));
    return () => {
      alive = false;
    };
  }, [key, rev, native, modelId]);
  return { native, pending: native && !nv && !failed, nv, rows, setRows: (fn) => setRowsState((rs) => (rs ? fn(rs) : rs)) };
}
