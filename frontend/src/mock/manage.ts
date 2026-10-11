// 3차(phase3.md §3, §5, §7) 목 핸들러: Study 이름 변경·보관·보관 해제, 작업 재시도, 용량·정리(manageStorage.ts).
// F5 보류(architecture.md §1.5)로 phase2.ts에 넣지 않고 server.ts 라우팅 1곳에서 위임한다.
// 목 ID는 server의 공유 카운터(nid)를 요청 처리 때만 쓴다(시드 생성 뒤).
import type { Job, Me } from "../api/types";
import type { MockResp, MockServer } from "./server";
import { StorageMock } from "./manageStorage";

const TERMINAL = ["SUCCEEDED", "FAILED", "CANCELED", "INTERRUPTED"];
const err = (status: number, code: string, message: string, extra: Record<string, unknown> = {}): MockResp => ({
  status,
  body: { detail: { code, message, ...extra } },
});

export class ManageMock {
  /** 시험용: 보관 해제 시 폴더가 없는 Study(409 STUDY_FOLDER_MISSING) */
  missingFolders = new Set<string>();

  /** 3차 S3 용량·정리(phase3.md §5) */
  storage: StorageMock;

  constructor(private s: MockServer) {
    this.storage = new StorageMock(s);
  }

  private needPower(projectId: string): MockResp | null {
    const r = this.s.role(projectId);
    return r === "power" || r === "admin" ? null : err(403, "PERMISSION_DENIED", "실행 권한(power 이상)이 필요합니다", { required: "power" });
  }

  handle(method: string, seg: string[], body: Record<string, unknown> | null, me: Me): MockResp | null {
    if (seg[0] === "studies" && seg[1] && (method === "PATCH" && !seg[2] || method === "POST" && (seg[2] === "archive" || seg[2] === "unarchive") && !seg[3]))
      return this.study(method, seg[1], seg[2], body);
    if (method === "POST" && seg[0] === "jobs" && seg[1] && seg[2] === "retry" && !seg[3]) return this.retry(seg[1], me);
    if (seg[0] === "studies" && seg[1] && !seg[3] && ((method === "GET" && seg[2] === "storage") || (method === "POST" && seg[2] === "jobs")))
      return this.studyStorage(method, seg[1], body);
    return null;
  }

  private studyStorage(method: string, id: string, body: Record<string, unknown> | null): MockResp | null {
    const st = this.s.studies.find((x) => x.id === id);
    if (!st) return err(404, "NOT_FOUND", "Study를 찾을 수 없습니다");
    if (method === "GET") return this.storage.report(st);
    const d = this.needPower(st.project_id);
    if (d) return d;
    return this.storage.createJob(st, String(body?.job_type), (body?.params ?? {}) as Record<string, unknown>);
  }

  private study(method: string, id: string, sub: string | undefined, body: Record<string, unknown> | null): MockResp {
    const st = this.s.studies.find((x) => x.id === id);
    if (!st) return err(404, "NOT_FOUND", "Study를 찾을 수 없습니다");
    const d = this.needPower(st.project_id);
    if (d) return d;
    const touch = () => {
      st.version++;
      st.updated_at = new Date().toISOString();
    };
    if (method === "PATCH") {
      const title = String(body?.title ?? "").trim();
      if (!title || title.length > 120) return err(422, "INVALID_PARAMS", "제목은 1~120자입니다");
      if (Number(body?.version) !== st.version) return err(409, "VERSION_CONFLICT", "다른 사용자가 먼저 수정했습니다. 새로 고친 뒤 다시 시도하세요");
      st.title = title;
      touch();
    } else if (sub === "archive") {
      if (this.s.jobs.some((j) => j.study_id === st.id && !TERMINAL.includes(j.state)))
        return err(409, "STUDY_HAS_ACTIVE_JOB", "대기 중이거나 실행 중인 작업이 있어 보관할 수 없습니다");
      if (st.status !== "ARCHIVED") {
        st.status = "ARCHIVED";
        touch();
      }
    } else if (st.status !== "ACTIVE") {
      if (this.missingFolders.has(st.id)) return err(409, "STUDY_FOLDER_MISSING", "AI 루트에서 Study 폴더를 찾을 수 없습니다");
      st.status = "ACTIVE";
      touch();
    }
    return { status: 200, body: this.s.studyOut(st) };
  }

  private retry(id: string, me: Me): MockResp {
    const old = this.s.jobs.find((j) => j.id === id);
    if (!old) return err(404, "NOT_FOUND", "작업을 찾을 수 없습니다");
    if (old.created_by === me.user_id) {
      const d = this.needPower(old.project_id);
      if (d) return d;
    } else if (!me.is_global_admin) return err(403, "PERMISSION_DENIED", "전역 관리자 권한이 필요합니다", { required: "global_admin" });
    if (!TERMINAL.includes(old.state) || old.state === "SUCCEEDED") return err(409, "JOB_NOT_RETRYABLE", "실패·취소·중단된 작업만 재시도할 수 있습니다");
    if (old.job_type.startsWith("STUDY_")) return err(409, "JOB_NOT_RETRYABLE", "이 작업은 재시도 대신 새로 실행하세요");
    const st = this.s.studies.find((x) => x.id === old.study_id)!;
    const busy = this.storage.cleanupGate(st.id);
    if (busy) return busy;
    const r = this.s.createJob(st, old.job_type, { ...old.params });
    if (r.status !== 201) return r;
    const nj = r.body as Job;
    nj.retry_of_job_id = old.id;
    return r;
  }
}
