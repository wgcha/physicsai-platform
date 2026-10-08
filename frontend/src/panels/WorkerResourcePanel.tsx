import { useCallback, useState } from "react";
import { api, type Resources } from "../api";
import { useApp } from "../app/AppContext";
import { usePolling } from "../hooks/usePolling";
import { POLL } from "../lib/poll";

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
    <section className="panel" aria-label="워커 자원">
      <header className="panel-head">
        <h2>워커 자원</h2>
        {status && (
          <span className={`worker-state ${offline ? "off" : "on"}`}>{offline ? "워커 오프라인" : "워커 정상"}</span>
        )}
      </header>
      {offline && <div className="warn-box small">워커가 응답하지 않습니다. 등록한 작업은 대기열에 남아 있다가 워커가 돌아오면 실행됩니다.</div>}
      {!r ? (
        <div className="empty small">{none ? "자원 정보 없음" : "불러오는 중…"}</div>
      ) : (
        <>
          <Meter label="CPU" pct={r.cpu_pct} text={`${Math.round(r.cpu_pct)}%`} />
          <Meter label="RAM" pct={(r.ram_used_gb / r.ram_total_gb) * 100} text={`${r.ram_used_gb.toFixed(0)} / ${r.ram_total_gb.toFixed(0)} GB`} />
          {r.gpu.map((g, i) => (
            <Meter key={i} label={r.gpu.length > 1 ? `GPU${i}` : "GPU"} pct={g.util_pct} text={`${Math.round(g.util_pct)}% · ${(g.mem_used_mb / 1024).toFixed(1)}/${(g.mem_total_mb / 1024).toFixed(0)} GB`} />
          ))}
          <div className="limits small">
            유효 한도 {r.limits.cores}코어 · {r.limits.memory_gb}GB · {PRIORITY_LABEL[r.limits.priority] ?? r.limits.priority}
            {!r.limits.cpu_cap_enforced && <span className="muted"> · CPU 상한 미적용(개발 환경)</span>}
          </div>
        </>
      )}
    </section>
  );
}
