// S20(D3-68): ①-4·④ 공용 "Radioss 버전" 칸 — gateway scx일 때만 보이고, 초기값 = /status hpc.scx_version(없으면 26.1).
import { useEffect, useState } from "react";
import { useApp } from "../app/AppContext";
import { HPC_VERSION_DEFAULT, hpcVersionError, hpcVersionPayload } from "../lib/hpcVersion";
import { useScxMode } from "./HpcScx";

export interface RadiossVersionState {
  show: boolean;
  value: string;
  setValue: (v: string) => void;
  error: string | null;
  /** 요청 hpc.version — scx가 아니거나 초기값 그대로면 null */
  payload: string | null;
}

export function useRadiossVersion(): RadiossVersionState {
  const { status } = useApp();
  const show = useScxMode();
  const initial = status?.hpc.scx_version || HPC_VERSION_DEFAULT;
  const [value, setValue] = useState(initial);
  const [touched, setTouched] = useState(false);
  useEffect(() => {
    if (!touched) setValue(initial);
  }, [initial, touched]);
  const error = show ? hpcVersionError(value) : null;
  return {
    show,
    value,
    setValue: (v) => (setTouched(true), setValue(v)),
    error,
    payload: show && !error ? hpcVersionPayload(value, initial) : null,
  };
}

export function RadiossVersionField({ state }: { state: RadiossVersionState }) {
  if (!state.show) return null;
  return (
    <label className="field">
      <span className="field-label">Radioss 버전</span>
      <input
        type="text"
        className="mono"
        aria-label="Radioss 버전"
        aria-invalid={!!state.error}
        value={state.value}
        spellCheck={false}
        onChange={(e) => state.setValue(e.target.value)}
      />
      {state.error && (
        <span className="error-text small" role="alert">
          {state.error}
        </span>
      )}
    </label>
  );
}
