// 3차 S3(phase3.md §5) 목: Study 용량 계산·정리. manage.ts가 위임한다.
// 파일 시스템 흉내 = Study별 고정 후보 목록 + 옮긴 rel 집합. 작업 진행은 server.tick(engine.ts)이 하고 끝날 때 onFinish가 결과를 채운다.
import type { CategoryKey, Job, Study, StorageCategory } from "../api/types";
import type { MockResp, MockServer } from "./server";

const TERMINAL = ["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"];
const SCAN = "STUDY_STORAGE_SCAN";
const CLEANUP = "STUDY_CLEANUP";
const GB = 1024 ** 3;
const MB = 1024 ** 2;
const err = (status: number, code: string, message: string, extra: Record<string, unknown> = {}): MockResp => ({
  status,
  body: { detail: { code, message, ...extra } },
});

const CATS: { key: CategoryKey; label: string; impact: string; items: [string, number, string | null][] }[] = [
  { key: "PACKAGE_PSDATA", label: "학습 패키지 사본(psdata)", impact: "학습 패키지가 '없음'으로 바뀝니다. ③-2 '학습 패키지 내보내기'로 다시 만들 수 있습니다.",
    items: [["03_package/ds-2", 2.4 * GB, "데이터셋 ds-2"]] },
  { key: "SCORE_PREDICTIONS", label: "평가 예측 psdata", impact: "평가 점수는 그대로입니다. 다시 평가하면 새로 생깁니다.",
    items: [["03_model/score/m-2/j-ev2/predictions.psdata", 640 * MB, "모델 cushion_TNS v2 평가"], ["03_model/score/m-1/j-ev0/predictions.psdata", 610 * MB, "모델 cushion_TNS v1 평가"]] },
  { key: "CURATED_H3D", label: "정리된 h3d(②)", impact: "이 큐레이션으로 ③-1 데이터셋을 새로 만들 수 없습니다(이미 만든 데이터셋은 그대로).",
    items: [["02_curated/cu-1/CURATED_DATA", 5.2 * GB, "데이터셋 1개가 이 큐레이션으로 만들어짐"]] },
  { key: "PREDICT_INPUT", label: "예측 Radioss 입력(④)", impact: "'입력파일 받기'와 PBS 검증 재실행을 할 수 없습니다. 예측 결과·컨투어는 그대로입니다.",
    items: [["04_predict/j-pred/INPUT", 180 * MB, "예측 작업 j-pred"]] },
  { key: "PREVIEW_OUTPUT", label: "② 미리보기 산출", impact: "지난 미리보기 화면은 '결과 파일 없음'으로 보입니다. 다시 실행하면 새로 생깁니다.", items: [] },
  { key: "JOB_LOGS", label: "작업 로그", impact: "해당 작업의 로그 보기와 오류 묶음의 로그 부분을 쓸 수 없습니다.",
    items: [["logs/j-old1", 12 * MB, "데이터셋 생성 · SUCCEEDED"], ["logs/j-old2", 3 * MB, "모델 등록 · FAILED"]] },
];
const FOLDERS: [string, number, number][] = [
  ["00_inbox", 1.1 * GB, 420], ["01_train", 38 * GB, 9120], ["02_curated", 5.3 * GB, 1810], ["02_preview", 40 * MB, 12],
  ["03_dataset", 7.5 * GB, 8], ["03_package", 2.4 * GB, 3], ["03_model", 2.2 * GB, 31], ["04_params", 2 * MB, 6],
  ["04_predict", 900 * MB, 220], ["05_opt", 1.4 * GB, 640], ["logs", 60 * MB, 410], ["(기타)", 4096, 1],
];

export class StorageMock {
  private moved = new Map<string, Map<string, [number, string]>>(); // study → rel → [bytes, category]

  constructor(private s: MockServer) {}

  private movedOf(sid: string) {
    if (!this.moved.has(sid)) this.moved.set(sid, new Map());
    return this.moved.get(sid)!;
  }

  private jobsOf(sid: string, type: string) {
    return this.s.jobs.filter((j) => j.study_id === sid && j.job_type === type);
  }

  private latest(sid: string, type: string, pred: (j: Job) => boolean) {
    return this.jobsOf(sid, type).filter(pred).sort((a, b) => (b.finished_at ?? "").localeCompare(a.finished_at ?? ""))[0] ?? null;
  }

  private active(sid: string, type: string) {
    return this.jobsOf(sid, type).find((j) => !TERMINAL.includes(j.state))?.id ?? null;
  }

  private staleReason(sid: string, scan: Job | null): string | null {
    if (!scan) return "아직 계산하지 않았습니다";
    const after = this.s.jobs.filter((j) => j.study_id === sid && j.job_type !== SCAN && j.finished_at && j.finished_at > (scan.started_at ?? "")).length;
    if (after) return `스캔 뒤 작업 ${after}개가 끝났습니다`;
    if (this.s.jobs.some((j) => j.study_id === sid && j.id !== scan.id && !TERMINAL.includes(j.state))) return "실행 중인 작업이 있습니다";
    return null;
  }

  cleanupRunning(sid: string): boolean {
    return !!this.active(sid, CLEANUP);
  }

  report(st: Study): MockResp {
    const scan = this.latest(st.id, SCAN, (j) => j.state === "SUCCEEDED");
    const reason = this.staleReason(st.id, scan);
    const last = this.latest(st.id, CLEANUP, (j) => TERMINAL.includes(j.state));
    const base = `D:\\PhysicsAI\\${st.folder_name}`;
    const r = (scan?.result ?? {}) as Record<string, unknown>;
    const lr = (last?.result ?? {}) as Record<string, unknown>;
    return {
      status: 200,
      body: {
        study_id: st.id, stale: reason !== null, stale_reason: reason,
        scan: scan ? { job_id: scan.id, started_at: scan.started_at, finished_at: scan.finished_at, ...r } : null,
        active_scan_job_id: this.active(st.id, SCAN), active_cleanup_job_id: this.active(st.id, CLEANUP),
        last_cleanup: last ? {
          job_id: last.id, state: last.state, finished_at: last.finished_at, categories: last.params.categories ?? [],
          moved_count: lr.moved_count ?? 0, moved_bytes: lr.moved_bytes ?? 0, skipped_count: lr.skipped_count ?? 0, skipped: lr.skipped ?? [],
          backup_rel: lr.backup_rel ?? null, backup_display_path: lr.backup_rel ? `${base}\\${String(lr.backup_rel).replace(/\//g, "\\")}` : null,
        } : null,
        study_display_path: base, backup_display_path: `${base}\\_backup`,
      },
    };
  }

  /** 정리 사전조건(§5.2 표). 통과하면 null */
  precheck(st: Study, params: Record<string, unknown>): MockResp | null {
    const cats = (params.categories ?? []) as CategoryKey[];
    if (!Array.isArray(cats) || !cats.length || new Set(cats).size !== cats.length) return err(422, "INVALID_PARAMS", "범주를 1~6개, 중복 없이 고르세요");
    const scan = this.latest(st.id, SCAN, (j) => j.state === "SUCCEEDED");
    const stale = "용량 계산 결과가 최신이 아닙니다. 다시 계산한 뒤 정리하세요";
    if (!scan || scan.id !== params.scan_job_id) return err(409, "STORAGE_SCAN_STALE", stale);
    if (this.s.jobs.some((j) => j.study_id === st.id && !TERMINAL.includes(j.state)))
      return err(409, "STUDY_HAS_ACTIVE_JOB", "대기 중이거나 실행 중인 작업이 있어 정리할 수 없습니다");
    const reason = this.staleReason(st.id, scan);
    if (reason) return err(409, "STORAGE_SCAN_STALE", stale, { stale_reason: reason });
    const n = ((scan.result?.categories ?? []) as StorageCategory[]).filter((c) => cats.includes(c.key)).reduce((a, c) => a + c.item_count, 0);
    if (n < 1) return err(422, "INPUT_INVALID", "옮길 항목이 없습니다", { errors: [{ loc: ["params", "categories"], msg: "옮길 항목이 없습니다" }] });
    return null;
  }

  /** 작업 종료 시 결과 채우기. 성공 알림을 만들면 true(스캔은 false — R3-3) */
  onFinish(j: Job): boolean {
    if (j.job_type === SCAN) {
      j.result = this.scanResult(j.study_id);
      return false;
    }
    if (j.job_type === CLEANUP) {
      const scan = this.s.jobs.find((x) => x.id === j.params.scan_job_id);
      const cats = (j.params.categories ?? []) as CategoryKey[];
      const moved = ((scan?.result?.categories ?? []) as StorageCategory[])
        .filter((c) => cats.includes(c.key))
        .flatMap((c) => c.items.map((it) => ({ rel: it.rel, bytes: it.bytes, category: c.key })));
      const m = this.movedOf(j.study_id);
      for (const x of moved) m.set(x.rel, [x.bytes, x.category]);
      const stamp = (j.started_at ?? new Date().toISOString()).replace(/[-:]/g, "").replace(/\.\d+/, "");
      j.result = { moved, skipped: [], moved_count: moved.length, moved_bytes: moved.reduce((a, x) => a + x.bytes, 0), skipped_count: 0, backup_rel: `_backup/${stamp}_${j.id}` };
    }
    return true;
  }

  private scanResult(sid: string) {
    const m = this.movedOf(sid);
    const backup = [...m.values()].reduce((a, [b]) => a + b, 0);
    const minus = (key: string) => [...m.entries()].filter(([rel]) => rel.split("/")[0] === key).reduce((a, [, [b]]) => a + b, 0);
    const folders = FOLDERS.map(([key, bytes, files]) => ({ key, bytes: Math.max(0, Math.round(bytes - minus(key))), files }));
    if (backup) folders.push({ key: "_backup", bytes: backup, files: m.size });
    const categories = CATS.map((c) => {
      const items = c.items.filter(([rel]) => !m.has(rel)).map(([rel, bytes, note]) => ({ rel, bytes: Math.round(bytes), files: 1, ref_id: rel.split("/")[1] ?? null, note }));
      return { key: c.key, label: c.label, impact: c.impact, truncated: false, item_count: items.length, total_bytes: items.reduce((a, x) => a + x.bytes, 0), items };
    });
    const total = folders.reduce((a, f) => a + f.bytes, 0);
    return {
      partial: false, total_bytes: total, total_files: folders.reduce((a, f) => a + f.files, 0), skipped_links: 0, errors: 0,
      backup_bytes: backup, backup_files: m.size, folders, categories,
      top_files: [
        { rel: "01_train/doe/run_0007/drop_0000.h3d", bytes: Math.round(1.9 * GB), modified_at: "2026-10-02T03:10:00Z", in_backup: false },
        { rel: "03_dataset/ds-2/train/dataset.psdata", bytes: Math.round(1.7 * GB), modified_at: "2026-10-05T06:00:00Z", in_backup: false },
        ...[...m.entries()].slice(0, 1).map(([rel, [b]]) => ({ rel: `_backup/x/${rel}`, bytes: b, modified_at: "2026-10-11T00:00:00Z", in_backup: true })),
      ],
    };
  }

  /** 정리 중 409(D3-24: 스캔 생성·Final 지정 PUT 포함). 아니면 null */
  cleanupGate(sid: string): MockResp | null {
    return this.cleanupRunning(sid) ? err(409, "STUDY_CLEANUP_RUNNING", "Study 정리가 진행 중입니다. 정리가 끝난 뒤 다시 실행하세요") : null;
  }

  /** POST /studies/{id}/jobs 중 관리 작업. 다른 유형은 null(정리 중이면 스캔 포함 모두 409 — D3-24) */
  createJob(st: Study, type: string, params: Record<string, unknown>): MockResp | null {
    const busy = this.cleanupGate(st.id);
    if (busy) return busy;
    if (type !== SCAN && type !== CLEANUP) return null;
    if (type === CLEANUP) {
      const pre = this.precheck(st, params);
      if (pre) return pre;
    }
    // 보관 Study에서도 생성 가능(R3-2): 서버 createJob의 보관 검사를 피해 ACTIVE 사본으로 만든다
    return this.s.createJob({ ...st, status: "ACTIVE" }, type, type === SCAN ? {} : { scan_job_id: params.scan_job_id, categories: params.categories });
  }
}
