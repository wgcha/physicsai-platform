// 분할 업로드(upload-report.md §6.7; esl-platform uploader 이식): 세션 만들기 → 파일별 청크 PUT(File.slice 스트리밍, 파이프라인 2청크)
// → 실패 시 지수 백오프 재시도·409 OFFSET_MISMATCH 는 서버 received 로 맞춤 → 이어 올리기(localStorage 세션 + 서버 received).
// sha256: 파일 전체 해시는 계산하지 않는다(30 GB 읽기 2회 방지). 청크(16 MB)마다 Web Crypto 로 계산해 X-Chunk-Sha256 헤더로 보낸다
// (crypto.subtle 이 없는 비보안 http 컨텍스트면 생략 — 서버는 크기·전체 sha256 으로 검증).
import { ApiError, errorMessage } from "../api";
import { uploadApi, type Upload, type UploadComplete, type UploadCreate, type UploadItemIn, type UploadPurpose } from "../api/uploads";

/** 파이프라인 깊이: 보내는 청크 1 + 미리 읽고 해시하는 청크 1(서버가 offset 순서를 검증해 PUT 은 동시에 1개) */
export const PARALLEL = 2;
export const DEFAULT_CHUNK = 16 * 1024 ** 2;
/** 업로드 전 예상 시간 계산용 사내망 가정 속도(실측 전) */
export const ASSUMED_BPS = 30 * 1024 ** 2;
const STORE = "pai.upload.";

export interface PickedFile {
  file: File;
  /** 선택 폴더 기준 상대경로('/' 구분, 파일 이름 포함) */
  rel: string;
}

export type UploadPhase = "idle" | "uploading" | "paused" | "error" | "uploaded" | "completing" | "done" | "canceled";

export interface UploadProgress {
  phase: UploadPhase;
  /** 파일별 서버가 받은 바이트 */
  received: number[];
  sent: number;
  total: number;
  /** 지금 보내는 파일 번호 */
  current: number;
  /** 실측 전송 속도(B/s), 모르면 null */
  rate: number | null;
  retries: number;
  error: string | null;
  uploadId: string | null;
  /** 이 브라우저에 남아 있던 세션을 서버 received 부터 이어 올리는 중 */
  resumed: boolean;
}

export interface UploaderDeps {
  createUpload: (studyId: string, body: UploadCreate) => Promise<Upload>;
  getUpload: (id: string) => Promise<Upload>;
  addUploadFiles: (id: string, files: UploadItemIn[]) => Promise<Upload>;
  completeUpload: (id: string) => Promise<UploadComplete>;
  cancelUpload: (id: string) => Promise<void>;
  putChunk: (id: string, index: number, offset: number, blob: Blob, sha256?: string | null) => Promise<{ received: number; done: boolean }>;
  hash: (b: Blob) => Promise<string | null>;
  sleep: (ms: number) => Promise<void>;
  now: () => number;
}

const defaultDeps: UploaderDeps = {
  createUpload: uploadApi.create,
  getUpload: uploadApi.get,
  addUploadFiles: uploadApi.addFiles,
  completeUpload: uploadApi.complete,
  cancelUpload: uploadApi.cancel,
  putChunk: uploadApi.putChunk,
  hash: sha256Hex,
  sleep: (ms) => new Promise((r) => setTimeout(r, ms)),
  now: () => Date.now(),
};

export interface UploadTarget {
  studyId: string;
  purpose: UploadPurpose;
  name: string;
  engine?: "native" | "altair" | null;
}

/** 청크 시작 오프셋 목록(from 부터) */
export function planChunks(size: number, chunk: number, from = 0): { offset: number; end: number }[] {
  const out: { offset: number; end: number }[] = [];
  for (let o = from; o < size; o += chunk) out.push({ offset: o, end: Math.min(size, o + chunk) });
  return out;
}

export function sha256Available(): boolean {
  return typeof crypto !== "undefined" && !!crypto.subtle && typeof crypto.subtle.digest === "function";
}

/** File.slice 한 조각만 메모리로(Blob.arrayBuffer 가 없는 환경은 FileReader) */
function readBuf(blob: Blob): Promise<ArrayBuffer> {
  if (typeof blob.arrayBuffer === "function") return blob.arrayBuffer();
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(r.result as ArrayBuffer);
    r.onerror = () => rej(r.error);
    r.readAsArrayBuffer(blob);
  });
}

export async function sha256Hex(blob: Blob): Promise<string | null> {
  if (!sha256Available()) return null;
  try {
    const h = await crypto.subtle.digest("SHA-256", new Uint8Array(await readBuf(blob)));
    return [...new Uint8Array(h)].map((b) => b.toString(16).padStart(2, "0")).join("");
  } catch {
    return null;
  }
}

type Saved = { upload_id: string; files: [string, number, number][] };
export const storeKey = (studyId: string, purpose: string) => `${STORE}${studyId}.${purpose}`;
const fileSig = (files: PickedFile[]): [string, number, number][] => files.map((f) => [f.rel, f.file.size, f.file.lastModified]);
const sameSig = (a: Saved["files"], b: Saved["files"]) => a.length === b.length && a.every((x, i) => x[0] === b[i][0] && x[1] === b[i][1] && x[2] === b[i][2]);

function storeGet(key: string): Saved | null {
  try {
    const v = localStorage.getItem(key);
    return v ? (JSON.parse(v) as Saved) : null;
  } catch {
    return null;
  }
}
function storeSet(key: string, v: Saved | null) {
  try {
    if (v) localStorage.setItem(key, JSON.stringify(v));
    else localStorage.removeItem(key);
  } catch {
    /* 저장소 없음 */
  }
}

/** 이 브라우저에 같은 파일 묶음의 이어 올릴 세션이 있는가(고른 직후 안내용 — 서버 상태는 올리기 때 확인) */
export function hasSavedSession(studyId: string, purpose: string, files: PickedFile[]): boolean {
  const s = storeGet(storeKey(studyId, purpose));
  return !!s && sameSig(s.files, fileSig(files));
}

export function etaText(bytesLeft: number, bps: number): string {
  const s = Math.max(1, Math.round(bytesLeft / bps));
  if (s < 60) return `${s}초`;
  if (s < 3600) return `${Math.round(s / 60)}분`;
  return `${Math.floor(s / 3600)}시간 ${Math.round((s % 3600) / 60)}분`;
}

export class Uploader {
  files: PickedFile[];
  uploadId: string | null = null;
  chunk = DEFAULT_CHUNK;
  maxRetries: number;
  retryDelayMs: number;
  private deps: UploaderDeps;
  private stopped = false;
  private p: UploadProgress;
  private key: string;
  private t0 = 0;
  private sent0 = 0;
  private doneFlags: boolean[];
  private canceled = false;

  constructor(
    public target: UploadTarget,
    files: PickedFile[],
    private onProgress: (p: UploadProgress) => void = () => undefined,
    opts: { deps?: Partial<UploaderDeps>; maxRetries?: number; retryDelayMs?: number; chunkSize?: number } = {},
  ) {
    this.files = [...files];
    this.deps = { ...defaultDeps, ...opts.deps };
    this.maxRetries = opts.maxRetries ?? 5;
    this.retryDelayMs = opts.retryDelayMs ?? 1000;
    if (opts.chunkSize) this.chunk = opts.chunkSize;
    this.key = storeKey(target.studyId, target.purpose);
    this.doneFlags = files.map(() => false);
    this.p = { phase: "idle", received: files.map(() => 0), sent: 0, total: this.total(), current: 0, rate: null, retries: 0, error: null, uploadId: null, resumed: false };
  }

  total() {
    return this.files.reduce((s, f) => s + f.file.size, 0);
  }

  private emit(patch: Partial<UploadProgress>) {
    if (this.canceled && patch.phase !== "canceled") return; // 취소 뒤 늦게 끝나는 청크 응답이 화면을 되살리지 않게
    this.p = { ...this.p, ...patch };
    this.p.sent = this.p.received.reduce((a, b) => a + b, 0);
    this.p.total = this.total();
    const dt = (this.deps.now() - this.t0) / 1000;
    if (this.p.phase === "uploading" && dt > 0.5) this.p.rate = (this.p.sent - this.sent0) / dt;
    this.onProgress({ ...this.p, received: [...this.p.received] });
  }

  get progress() {
    return this.p;
  }

  stop() {
    this.stopped = true;
  }

  private specs(files: PickedFile[]): UploadItemIn[] {
    return files.map((f) => ({ rel: f.rel, size: f.file.size }));
  }

  private matchesServer(st: Upload): boolean {
    return st.files.length === this.files.length && st.files.every((x, i) => x.rel === this.files[i].rel && x.size === this.files[i].file.size);
  }

  /** 세션 확보: 저장된 세션이 살아 있고 같은 파일 묶음이면 서버 received 로 이어 올리기 */
  private async ensureSession(): Promise<Upload> {
    if (this.uploadId) return this.deps.getUpload(this.uploadId);
    const saved = storeGet(this.key);
    if (saved && sameSig(saved.files, fileSig(this.files))) {
      try {
        const st = await this.deps.getUpload(saved.upload_id);
        if (st.state !== "OPEN" || !this.matchesServer(st)) throw new Error(st.state);
        this.uploadId = saved.upload_id;
        this.chunk = st.chunk_size || this.chunk;
        this.p.resumed = st.files.some((x) => x.received > 0);
        return st;
      } catch {
        storeSet(this.key, null);
      }
    } else if (saved) {
      storeSet(this.key, null);
    }
    const created = await this.deps.createUpload(this.target.studyId, { purpose: this.target.purpose, name: this.target.name, engine: this.target.engine ?? undefined, files: this.specs(this.files) });
    this.uploadId = created.upload_id;
    this.chunk = created.chunk_size || this.chunk;
    storeSet(this.key, { upload_id: created.upload_id, files: fileSig(this.files) });
    return created;
  }

  /** 올리기 시작 또는 이어 올리기. 끝까지 보냈으면 true */
  async run(): Promise<boolean> {
    this.stopped = false;
    try {
      const st = await this.ensureSession();
      this.doneFlags = this.files.map((_, i) => !!st.files.find((x) => x.index === i)?.done);
      const received = this.files.map((f, i) => (this.doneFlags[i] ? f.file.size : st.files.find((x) => x.index === i)?.received ?? this.p.received[i] ?? 0));
      this.t0 = this.deps.now();
      this.sent0 = received.reduce((a, b) => a + b, 0);
      this.emit({ phase: "uploading", received, uploadId: this.uploadId, error: null, rate: null });
      for (let i = 0; i < this.files.length; i++) {
        if (!(await this.sendFile(i))) {
          this.emit({ phase: "paused" });
          return false;
        }
      }
      this.emit({ phase: "uploaded" });
      return true;
    } catch (e) {
      this.emit({ phase: "error", error: errorMessage(e) });
      return false;
    }
  }

  /** 파일 i 를 received 부터 청크로. 서버가 offset 순서를 검증하므로 PUT 은 한 번에 1개, 다음 청크 읽기·sha256 은
   *  앞 청크 전송 중에 미리(파이프라인 PARALLEL=2). 멈춤이면 false, 실패면 throw */
  private async sendFile(i: number): Promise<boolean> {
    const f = this.files[i].file;
    let offset = this.p.received[i];
    if (this.doneFlags[i] || (offset >= f.size && f.size > 0)) return true;
    const prep = (off: number) => {
      const blob = f.slice(off, Math.min(f.size, off + this.chunk));
      return { off, blob, sha: this.deps.hash(blob) };
    };
    // 0바이트 파일은 빈 청크 1개로 완료시킨다(서버가 received == size 에서 done 처리)
    let cur: ReturnType<typeof prep> | null = offset < f.size || f.size === 0 ? prep(offset) : null;
    let fails = 0;
    while (cur) {
      if (this.stopped) return false;
      if (cur.off !== offset) cur = prep(offset);
      const nextOff = cur.off + cur.blob.size;
      const ahead = nextOff < f.size ? prep(nextOff) : null; // 미리 읽기·해시(최대 2청크 메모리)
      try {
        const r = await this.deps.putChunk(this.uploadId!, i, cur.off, cur.blob, await cur.sha);
        offset = r.received;
        fails = 0;
        if (r.done) this.doneFlags[i] = true;
        cur = !r.done && offset < f.size ? (ahead && ahead.off === offset ? ahead : prep(offset)) : null;
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          // 순서 어긋남·이미 받음 → 서버 received 로 맞춤(UPLOAD_FILE_DONE 은 received = size)
          const rec = typeof e.detail.received === "number" ? (e.detail.received as number) : (await this.deps.getUpload(this.uploadId!)).files.find((x) => x.index === i)?.received;
          if (typeof rec === "number" && (rec !== offset || e.code === "UPLOAD_FILE_DONE")) {
            offset = rec;
            if (e.code === "UPLOAD_FILE_DONE" || rec >= f.size) this.doneFlags[i] = true;
            cur = !this.doneFlags[i] && offset < f.size ? prep(offset) : null;
            this.bump(i, offset);
            continue;
          }
          throw e;
        }
        // 4xx(408·429 제외, 청크 sha 불일치는 재전송)·507 은 사용자가 고쳐야 하므로 즉시 실패
        const status = e instanceof ApiError ? e.status : 0;
        const retryable = status === 0 || (status >= 500 && status !== 507) || status === 408 || status === 429 || (e instanceof ApiError && e.code === "CHUNK_SHA256_MISMATCH");
        if (!retryable) throw e;
        fails += 1;
        this.p.retries += 1;
        if (fails > this.maxRetries) throw e;
        await this.deps.sleep(this.retryDelayMs * 2 ** (fails - 1));
        continue;
      }
      this.bump(i, offset);
    }
    return true;
  }

  private bump(i: number, offset: number) {
    const rec = [...this.p.received];
    rec[i] = offset;
    this.emit({ received: rec, current: i });
  }

  /** inspect 실패(파일 누락 등) 후 파일을 더해 이어 올리기 */
  async add(files: PickedFile[]): Promise<boolean> {
    if (!this.uploadId) throw new Error("업로드 세션이 없습니다");
    await this.deps.addUploadFiles(this.uploadId, this.specs(files));
    this.files.push(...files);
    this.doneFlags.push(...files.map(() => false));
    this.p.received.push(...files.map(() => 0));
    storeSet(this.key, { upload_id: this.uploadId, files: fileSig(this.files) });
    return this.run();
  }

  /** complete: COMPLETED 면 저장 세션을 지운다. inspect 실패면 OPEN 유지(phase = uploaded) */
  async complete(): Promise<UploadComplete> {
    this.emit({ phase: "completing" });
    try {
      const r = await this.deps.completeUpload(this.uploadId!);
      const ok = r.state === "COMPLETED";
      if (ok) storeSet(this.key, null);
      this.emit({ phase: ok ? "done" : "uploaded" });
      return r;
    } catch (e) {
      this.emit({ phase: "uploaded", error: errorMessage(e) });
      throw e;
    }
  }

  /** 취소: 멈추고 서버 세션을 취소(받은 것은 서버가 _backup 으로) — 세션이 없으면 로컬만 */
  async cancel(): Promise<void> {
    this.stopped = true;
    const id = this.uploadId;
    storeSet(this.key, null);
    this.emit({ phase: "canceled" });
    this.canceled = true;
    if (id) await this.deps.cancelUpload(id);
  }
}
