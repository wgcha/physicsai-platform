// 운영 목 라우트·상태: me·프로젝트·상태·대기열·자원(§10.2), 알림(§10.7), 환경 점검(phase2.md §11 — 시드·진행·라우트).
import type { EnvCheck, EnvCheckItem } from "../api/types";
import { PROJECTS, iso } from "./data";
import { err, needAdmin, ok, type Route } from "./route";
import type { Phase2Mock } from "./phase2";
import { queued, refreshPositions } from "./engine";
import { summary } from "./jobs";

function envItems(variant: number, pendingWorker = false): EnvCheckItem[] {
  const it = (key: string, category: EnvCheckItem["category"], label: string, status: EnvCheckItem["status"], message: string, source: "API" | "WORKER", detail: Record<string, unknown> | null = null): EnvCheckItem => ({
    key, category, label, status, message, source, detail,
  });
  const api: EnvCheckItem[] = [
    it("config.valid", "CONFIG", "설정 검증", "OK", "설정 오류 없음", "API"),
    it("db.connection", "DATABASE", "DB 연결", "OK", "SELECT 1 성공", "API", { latency_ms: 3 }),
    it("db.migration_head", "DATABASE", "마이그레이션 버전", "OK", "0002_phase2", "API", { current: "0002_phase2", head: "0002_phase2" }),
    it("auth.dashboard", "AUTH", "대시보드 인증", "OK", "introspection 200", "API", { latency_ms: 41 }),
    it("auth.projects", "AUTH", "대시보드 프로젝트", "OK", "프로젝트 3개", "API", { count: 3 }),
    it("hpc.gateway", "HPC", "PBS 연결", "WARN", "PBS 연결 안 됨", "API", { mode: "none" }),
    it("worker.heartbeat", "WORKER", "워커 heartbeat", "OK", "PHYSICS-PC:4412 · 4초 전", "API", { worker_id: "PHYSICS-PC:4412", age_s: 4, limiter: "windows_job" }),
  ];
  const W = (key: string, category: EnvCheckItem["category"], label: string, status: EnvCheckItem["status"], message: string, detail: Record<string, unknown> | null = null) =>
    pendingWorker ? it(key, category, label, "PENDING", "대기 중", "WORKER") : it(key, category, label, status, message, "WORKER", detail);
  const worker: EnvCheckItem[] = [
    W("altair.hyperstudy_path", "EXECUTABLE", "HyperStudy", "OK", "D:/Altair/2025/hwdesktop/hst/bin/win64/hstbatch.exe", { size: 512000, mtime: "2025-11-02T10:00:00Z" }),
    W("altair.simlab_path", "EXECUTABLE", "SimLab", "OK", "D:/Altair/2025/SimLab/SimLab.bat"),
    W("altair.edspy_path", "EXECUTABLE", "edspy", "OK", "D:/Altair/2025/PhysicsAI/edspy.exe"),
    W("altair.hw_exe_path", "EXECUTABLE", "HyperWorks", "OK", "D:/Altair/2025/hwdesktop/hw/bin/win64/hw.exe"),
    W("altair.hvtrans_exe_path", "EXECUTABLE", "hvtrans", variant ? "FAIL" : "OK", variant ? "파일이 없습니다: D:/Altair/2025/hwdesktop/io/hvtrans.exe" : "D:/Altair/2025/hwdesktop/io/hvtrans.exe"),
    W("altair.hstpy_path", "EXECUTABLE", "hstpy", "OK", "hstbatch 폴더에서 파생: hstpy.bat"),
    W("probe.edspy", "EXECUTABLE", "edspy 실행 시험", "SKIP", "존재 확인만(인자 미확인)"),
    W("resource.pyd_dir", "RESOURCE", "pyd 폴더", variant ? "FAIL" : "OK", variant ? "hst_gen_radioss_core*.pyd가 정확히 1개가 아닙니다: 0개" : "pyd 3개"),
    W("resource.preview_h3d_tcl", "RESOURCE", "h3d 미리보기 TCL", "OK", "BATCHRUN_preview_h3d.tcl"),
    W("resource.extract_minmax_tcl", "RESOURCE", "MinMax TCL", "WARN", "미설정(해당 기능 비활성)"),
    W("storage.ai_root.write", "STORAGE", "AI 루트 쓰기", "OK", "쓰기 시험 성공"),
    W("storage.ai_root.free", "STORAGE", "AI 루트 여유 공간", "OK", "여유 1.8 TB", { free_gb: 1843 }),
    W("storage.roots_overlap", "STORAGE", "루트 겹침", "OK", "겹침 없음"),
    W("storage.spdm_roots", "STORAGE", "SPDM 루트", "OK", "\\\\spdm\\master 읽기 가능"),
    W("worker.limiter", "WORKER", "자원 제한기", "OK", "windows_job · CPU 상한 적용", { name: "windows_job", cpu_cap_enforced: true }),
    W("worker.job_object", "WORKER", "Job Object 자체 시험", "OK", "CPU 50% · 64GB · below_normal", { cpu_rate: 5000, memory_gb: 64, priority: "below_normal" }),
    W("gpu.detect", "GPU", "GPU", "OK", "NVIDIA RTX A6000 (49152 MB)", { gpus: [{ name: "NVIDIA RTX A6000", memory_total_mb: 49152 }] }),
  ];
  return [...api, ...worker];
}

function summarize(items: EnvCheckItem[]) {
  const s = { ok: 0, warn: 0, fail: 0, skip: 0 };
  for (const i of items) {
    if (i.status === "OK") s.ok++;
    else if (i.status === "WARN") s.warn++;
    else if (i.status === "FAIL") s.fail++;
    else if (i.status === "SKIP") s.skip++;
  }
  return s;
}

/** 환경 점검 이력 시드 */
export function seedEnvChecks(p2: Phase2Mock) {
  const mk = (id: string, minAgo: number, variant: number): EnvCheck => {
    const items = envItems(variant);
    return {
      id, state: "DONE", requested_by_name: "박관리", created_at: iso(minAgo), finished_at: iso(minAgo - 1), started_at: iso(minAgo), expires_at: iso(minAgo - 15),
      worker_id: "PHYSICS-PC:4412", items, failure_message: null, summary: summarize(items), report_display_path: `E:\\shared\\AI_WORK\\_platform\\env_checks\\${id}\\report.json`,
    };
  };
  p2.envChecks.push(mk("ec-3", 95, 1), mk("ec-2", 60 * 26, 0), mk("ec-1", 60 * 24 * 3, 0));
}

/** 시간 1단계: 환경 점검 PENDING → RUNNING → DONE */
export function tickEnvChecks(p2: Phase2Mock) {
  for (const ec of p2.envChecks) {
    if (ec.state === "PENDING") {
      ec.state = "RUNNING";
      ec.started_at = new Date().toISOString();
      ec.worker_id = "PHYSICS-PC:4412:mock";
    } else if (ec.state === "RUNNING") {
      ec.items = envItems(1);
      ec.summary = summarize(ec.items);
      ec.state = "DONE";
      ec.finished_at = new Date().toISOString();
      ec.report_display_path = `E:\\shared\\AI_WORK\\_platform\\env_checks\\${ec.id}\\report.json`;
      p2.s.notify((ec as EnvCheck & { _uid?: string })._uid ?? "u-admin", "ENV_CHECK_DONE", null, `환경 점검 완료 — 실패 ${ec.summary.fail} · 경고 ${ec.summary.warn}`);
    }
  }
}

function ecOut(ec: EnvCheck): EnvCheck {
  const { _uid: _u, ...rest } = ec as EnvCheck & { _uid?: string };
  return rest;
}

/** §10.2: me·프로젝트·상태·대기열(이동)·자원 */
export const opsRoutes: Route = (srv, { method, path, seg, query, body, headers, me }) => {
  if (method === "GET" && path === "/me") return { status: 200, body: me };
  if (method === "GET" && path === "/projects") return { status: 200, body: PROJECTS };
  if (method === "GET" && path === "/status")
    return {
      status: 200,
      body: {
        config: { ok: true, errors: [], warnings: srv.configWarnings },
        worker: { online: true, worker_id: "PHYSICS-PC:4412:mock", last_seen_at: new Date().toISOString(), limiter: "windows_job" },
        hpc: srv.hpcConfigured ? { mode: "command", configured: true, message: "PBS command 모드", collect_mode: "in_place" } : { mode: "none", configured: false, message: "PBS 연결 안 됨", collect_mode: "in_place" },
        altair: [{ key: "edspy_path", ok: true }, { key: "simlab_path", ok: true }, { key: "hw_exe_path", ok: true }],
        templates: [{ key: "geom_update", configured: true }, { key: "mesh", configured: false }, { key: "response_extract", configured: false }],
        limits: { configured: {}, detected: {}, effective: {} },
        ui: srv.ui,
        auth: { mode: "dashboard", login_url: srv.loginUrl },
        demo: srv.demo,
        ...srv.p2.status(me.is_global_admin),
      },
    };
  if (method === "GET" && path === "/queue") {
    refreshPositions(srv);
    const running = srv.jobs.find((j) => j.state === "RUNNING" && j.lane === "SLOT") ?? null;
    const lightRun = srv.jobs.find((j) => j.state === "RUNNING" && j.lane === "LIGHT") ?? null;
    return {
      status: 200,
      body: {
        slot: { holder_job_id: running?.id ?? null, since: running?.started_at ?? null },
        running: running ? summary(srv, running) : null,
        queued: queued(srv, "SLOT").map((j) => summary(srv, j)),
        light: { running: lightRun ? summary(srv, lightRun) : null, queued: queued(srv, "LIGHT").map((j) => summary(srv, j)) },
        waiting_hpc: srv.jobs.filter((j) => j.state === "WAITING_HPC").map((j) => summary(srv, j)),
        collecting: srv.jobs.filter((j) => j.state === "COLLECTING").map((j) => summary(srv, j)),
      },
    };
  }
  if (method === "POST" && seg[0] === "queue" && seg[2] === "move") {
    const d = needAdmin(me);
    if (d) return d;
    const list = queued(srv, "SLOT");
    const idx = list.findIndex((j) => j.id === seg[1]);
    if (idx < 0) return err(409, "JOB_NOT_QUEUED", "대기 중인 작업이 아닙니다.");
    const pos = Number(body?.position);
    if (!Number.isInteger(pos) || pos < 1) return err(422, "INVALID_PARAMS", "position은 1 이상입니다.");
    const [j] = list.splice(idx, 1);
    list.splice(Math.min(pos - 1, list.length), 0, j);
    list.forEach((x) => srv.queueOrder.set(x.id, ++srv.queueSeq));
    refreshPositions(srv);
    return srv.handle("GET", "/queue", query, null, headers);
  }
  if (method === "GET" && path === "/resources") {
    const t = Date.now() / 1000;
    return {
      status: 200,
      body: {
        sampled_at: new Date().toISOString(),
        cpu_pct: 46 + 18 * Math.sin(t / 17),
        ram_used_gb: 41.5 + 6 * Math.sin(t / 23),
        ram_total_gb: 128,
        gpu: [{ name: "NVIDIA RTX A6000", util_pct: 71 + 12 * Math.sin(t / 11), mem_used_mb: 30720, mem_total_mb: 49152 }],
        gpu_status: "OK",
        gpu_message: "C:\\Windows\\System32\\nvidia-smi.exe",
        job: { job_id: "j-run", cpu_time_s: 5520, peak_memory_gb: 22.4 },
        limits: { cores: 32, cpu_rate: 5000, memory_gb: 64, priority: "below_normal", cpu_cap_enforced: true },
      },
    };
  }
  return null;
};

/** 환경 점검(전역 관리자) */
export const envCheckRoutes: Route = (srv, { method, seg, query, me }) => {
  const p2 = srv.p2;
  if (seg[0] === "admin" && seg[1] === "env-checks") {
    if (!me.is_global_admin) return err(403, "PERMISSION_DENIED", "전역 관리자만 할 수 있습니다.", { required: "global_admin" });
    if (method === "POST" && !seg[2]) {
      if (p2.envChecks.some((e) => e.state === "PENDING" || e.state === "RUNNING")) return err(409, "ENV_CHECK_BUSY", "이미 진행 중인 환경 점검이 있습니다.");
      const items = envItems(1, true);
      const ec: EnvCheck & { _uid?: string } = {
        id: p2.s.nid("ec"), state: "PENDING", requested_by_name: me.display_name, created_at: new Date().toISOString(), finished_at: null, started_at: null,
        expires_at: new Date(Date.now() + 900_000).toISOString(), worker_id: null, items, failure_message: null, summary: summarize(items), report_display_path: null, _uid: me.user_id,
      };
      p2.envChecks.unshift(ec);
      return ok(ecOut(ec), 202);
    }
    if (method === "GET" && !seg[2]) {
      const limit = Number(query.get("limit") ?? 20);
      const list = p2.envChecks.slice(0, limit).map(({ id, state, requested_by_name, created_at, finished_at, summary }) => ({ id, state, requested_by_name, created_at, finished_at, summary }));
      return ok(list);
    }
    if (method === "GET" && seg[2] === "latest") return p2.envChecks[0] ? ok(ecOut(p2.envChecks[0])) : err(404, "NOT_FOUND", "환경 점검 이력이 없습니다.");
    if (method === "GET" && seg[2]) {
      const ec = p2.envChecks.find((e) => e.id === seg[2]);
      return ec ? ok(ecOut(ec)) : err(404, "NOT_FOUND", "환경 점검을 찾을 수 없습니다.");
    }
  }
  return null;
};

/** §10.7 알림 */
export const notificationRoutes: Route = (srv, { method, seg, query, body, me }) => {
  if (seg[0] === "notifications") {
    const mine = srv.notifs.filter((n) => n.user_id === me.user_id);
    const unread = () => srv.notifs.filter((n) => n.user_id === me.user_id && !n.read_at).length;
    const maxSeq = Math.max(0, ...mine.map((n) => n.seq));
    if (method === "GET" && seg[1] === "unread-count") return { status: 200, body: { unread_count: unread(), max_seq: maxSeq } };
    if (method === "GET" && !seg[1]) {
      const after = query.get("after_seq");
      const limit = Number(query.get("limit") ?? 50);
      let items = [...mine].sort((a, b) => b.seq - a.seq);
      if (after !== null) items = items.filter((n) => n.seq > Number(after));
      return { status: 200, body: { items: items.slice(0, limit).map(({ user_id: _u, ...n }) => n), max_seq: maxSeq, unread_count: unread() } };
    }
    if (method === "POST" && seg[1] === "read") {
      const now = new Date().toISOString();
      if (body?.all) mine.forEach((n) => (n.read_at ??= now));
      else for (const s of (body?.seqs as number[]) ?? []) {
        const n = mine.find((x) => x.seq === s);
        if (n) n.read_at ??= now;
      }
      return { status: 200, body: { unread_count: unread() } };
    }
  }
  return null;
};
