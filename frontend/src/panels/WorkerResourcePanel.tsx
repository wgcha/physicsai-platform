import { useCallback, useState } from "react";
import { api, type Resources } from "../api";
import { useApp } from "../app/AppContext";
import { usePolling } from "../hooks/usePolling";
import { POLL } from "../lib/poll";
import { Cell } from "../design/Grid";

const PRIORITY_LABEL: Record<string, string> = { below_normal: "낮은 우선순위", normal: "보통 우선순위", idle: "유휴 우선순위" };

function Meter({ label, pct, text }: { label: string; pct: number; text: string }) {
  const p = Math.max(0, Math.min(100, pct));
  return (
    <div className="meter">
      <span className="meter-label">{label}</span>
      <span className="meter-track" role="meter" aria-label={label} aria-valuenow={Math.round(p)} aria-valuemin={0} aria-valuemax={100}>
        <span className={`meter-fill ${p > 90 ? "hot" : ""}`} style={{ width: `${p}%` }} />
      </span>
      <span className="meter-text">{text}</span>
    </div>
  );
}

/** GPU 목록이 비었을 때 회색 한 줄(phase3 D3-45 — 숨기지 않는다) */
export function gpuNoneText(r: Pick<Resources, "gpu_status">): string {
  if (r.gpu_status === "NOT_FOUND") return "GPU 정보 없음 — nvidia-smi를 찾지 못했습니다";
  if (r.gpu_status === "ERROR") return "GPU 정보 없음 — nvidia-smi 실행에 실패했습니다";
  return "GPU 정보 없음";
}

/** 워커 자원(§16.2 ②) */
export function WorkerResourcePanel() {
  const { status } = useApp();
  const [r, setR] = useState<Resources | null>(null);
  const [none, setNone] = useState(false);
  const load = useCallback(async () => {
    try {
      setR(await api.resources());
      setNone(false);
    } catch {
      setNone(true);
    }
  }, []);
  usePolling(load, POLL.resources);
  const offline = status && !status.worker.online;

  return (
    <Cell
      span={3}
      className="panel"
      label="워커 자원"
      title={<h2 className="T">워커 자원</h2>}
      refText={status ? <span className={`worker-state ${offline ? "off" : "on"}`}>{offline ? "워커 오프라인" : "워커 정상"}</span> : undefined}
    >
      {offline && <div className="warn-box small">워커가 응답하지 않습니다. 등록한 작업은 대기열에 남아 있다가 워커가 돌아오면 실행됩니다.</div>}
      {!r ? (
        <div className="empty small">{none ? "자원 정보 없음" : "불러오는 중…"}</div>
      ) : (
        <>
          {r.cpu_pct != null && <Meter label="CPU" pct={r.cpu_pct} text={`${Math.round(r.cpu_pct)}%`} />}
          {r.ram_used_gb != null && r.ram_total_gb ? (
            <Meter label="RAM" pct={(r.ram_used_gb / r.ram_total_gb) * 100} text={`${r.ram_used_gb.toFixed(0)} / ${r.ram_total_gb.toFixed(0)} GB`} />
          ) : null}
          {r.gpu.map((g, i) => (
            <Meter
              key={i}
              label={r.gpu.length > 1 ? `GPU${i}` : "GPU"}
              pct={g.util_pct ?? 0}
              text={`${g.util_pct != null ? Math.round(g.util_pct) + "%" : "–"}${g.mem_used_mb != null && g.mem_total_mb ? ` · ${(g.mem_used_mb / 1024).toFixed(1)}/${(g.mem_total_mb / 1024).toFixed(0)} GB` : ""}`}
            />
          ))}
          {r.gpu.length === 0 && (
            <div className="muted small gpu-none" data-testid="gpu-none" title={r.gpu_message ?? undefined}>
              {gpuNoneText(r)}
            </div>
          )}
          <div className="limits small">
            유효 한도 {r.limits.cores ?? "–"}코어 · {r.limits.memory_gb ?? "–"}GB · {r.limits.priority ? PRIORITY_LABEL[r.limits.priority] ?? r.limits.priority : "–"}
            {!r.limits.cpu_cap_enforced && <span className="muted"> · CPU 상한 미적용(개발 환경)</span>}
          </div>
        </>
      )}
    </Cell>
  );
}
