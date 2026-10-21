// upload-report.md §6.7·§13.1(V-UP-2·12): 분할 업로드(청크 분할·청크 sha256 헤더·OFFSET_MISMATCH 재개·재시도·취소·이어 올리기) — 목 서버(mock/uploads.ts) 기준.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MockServer, createMockFetch } from "../mock/server";
import { err } from "../mock/route";
import { Uploader, planChunks, sha256Available, sha256Hex, storeKey, type UploaderDeps } from "../lib/uploader";
import { uploadApi } from "../api/uploads";

const STUDY = "s-cushion";
const T = { studyId: STUDY, purpose: "MODEL_FOLDER" as const, name: "model_a" };
const file = (name: string, text: string, rel = name) => ({ file: new File([text], name), rel });

function setup() {
  const server = new MockServer({ user: "power", upload: true });
  server.up.chunkSize = 4;
  vi.stubGlobal("fetch", createMockFetch(server));
  return server;
}
const fast = { retryDelayMs: 0, deps: { sleep: async () => undefined } as Partial<UploaderDeps> };

describe("업로더 (V-UP-2·V-UP-12)", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("planChunks: 크기·시작점으로 청크 구간 계산", () => {
    expect(planChunks(10, 4)).toEqual([{ offset: 0, end: 4 }, { offset: 4, end: 8 }, { offset: 8, end: 10 }]);
    expect(planChunks(10, 4, 8)).toEqual([{ offset: 8, end: 10 }]);
    expect(planChunks(0, 4)).toEqual([]);
  });

  it("파일을 chunk_size 로 나눠 순서대로 PUT 하고 complete 가 경로를 돌려준다(여러 파일·0바이트 파일 포함)", async () => {
    const server = setup();
    const progress: number[] = [];
    const u = new Uploader(T, [file("a.psmdl", "0123456789"), file("empty.json", ""), file("b.log", "xyz")], (p) => progress.push(p.sent), fast);
    expect(await u.run()).toBe(true);
    expect(server.up.chunks.map((c) => [c.index, c.offset, c.size])).toEqual([[0, 0, 4], [0, 4, 4], [0, 8, 2], [1, 0, 0], [2, 0, 3]]);
    expect(u.progress).toMatchObject({ phase: "uploaded", sent: 13, total: 13 });
    expect(progress[progress.length - 1]).toBe(13);
    const r = await u.complete();
    expect(r.state).toBe("COMPLETED");
    expect(r.path).toMatch(/AI_WORK\\uploads\\.+_model_a$/);
    expect(localStorage.getItem(storeKey(STUDY, "MODEL_FOLDER"))).toBeNull(); // 완료 뒤 저장 세션 삭제
  });

  it("청크마다 sha256(Web Crypto)을 X-Chunk-Sha256 헤더로 보낸다 — hash 가 null(비보안 컨텍스트)이면 헤더 생략", async () => {
    const server = setup();
    const u = new Uploader(T, [file("a.psmdl", "abcdefgh")], undefined, { ...fast, deps: { ...fast.deps, hash: async (b) => (b.size === 4 ? "ab".repeat(32) : null) } });
    await u.run();
    expect(server.up.chunks.map((c) => c.sha)).toEqual(["ab".repeat(32), "ab".repeat(32)]);
    const server2 = setup();
    const u2 = new Uploader(T, [file("a.psmdl", "abcdefgh")], undefined, { ...fast, deps: { ...fast.deps, hash: async () => null } });
    await u2.run();
    expect(server2.up.chunks.map((c) => c.sha)).toEqual([null, null]);
    if (sha256Available()) {
      expect(await sha256Hex(new Blob(["abc"]))).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
      const server3 = setup();
      await new Uploader(T, [file("a.psmdl", "abcd")], undefined, fast).run();
      expect(server3.up.chunks[0].sha).toBe("88d4266fd4e6338d13b845fcf289579d209c897823b9217da3e161936f031589");
    }
  });

  it("409 UPLOAD_OFFSET_MISMATCH 는 서버 received 로 맞춰 계속한다(중복 전송·재시도 없이 마무리)", async () => {
    const server = setup();
    let first = true;
    const u = new Uploader(T, [file("a.psmdl", "0123456789")], undefined, {
      ...fast,
      deps: {
        ...fast.deps,
        putChunk: async (id, i, off, blob, sha) => {
          if (first) {
            first = false;
            await uploadApi.putChunk(id, i, 0, blob); // 응답을 놓친 첫 청크를 서버는 이미 받았다
          }
          return uploadApi.putChunk(id, i, off, blob, sha);
        },
      },
    });
    expect(await u.run()).toBe(true);
    expect(server.up.items[0].files[0]).toMatchObject({ received: 10, done: true });
    expect(server.up.chunks.map((c) => c.offset)).toEqual([0, 4, 8]);
    expect(u.progress.retries).toBe(0);
  });

  it("5xx·네트워크 오류는 지수 백오프로 재시도, 4xx(CHUNK_OVERFLOW)는 즉시 실패 후 같은 세션으로 이어 올리기", async () => {
    const server = setup();
    const waits: number[] = [];
    const u = new Uploader(T, [file("a.psmdl", "01234567")], undefined, { retryDelayMs: 100, deps: { sleep: async (ms) => void waits.push(ms) } });
    server.up.faults.push(err(503, "UPSTREAM", "일시 오류"), err(503, "UPSTREAM", "일시 오류"));
    expect(await u.run()).toBe(true);
    expect(waits).toEqual([100, 200]);
    expect(u.progress.retries).toBe(2);

    const server2 = setup();
    const u2 = new Uploader(T, [file("a.psmdl", "01234567")], undefined, fast);
    server2.up.faults.push(err(422, "CHUNK_OVERFLOW", "선언한 파일 크기를 넘는 청크입니다"));
    expect(await u2.run()).toBe(false);
    expect(u2.progress).toMatchObject({ phase: "error", error: "선언한 파일 크기를 넘는 청크입니다" });
    expect(await u2.run()).toBe(true); // 이어 올리기: 같은 세션
    expect(server2.up.items).toHaveLength(1);
  });

  it("재시도 상한(5회)을 넘으면 error", async () => {
    const server = setup();
    const u = new Uploader(T, [file("a.psmdl", "0123")], undefined, fast);
    for (let i = 0; i < 6; i++) server.up.faults.push(err(503, "UPSTREAM", "일시 오류"));
    expect(await u.run()).toBe(false);
    expect(u.progress).toMatchObject({ phase: "error", retries: 6 });
  });

  it("이어 올리기: 같은 파일 묶음을 다시 고르면 저장된 세션의 서버 received 부터(새 세션 만들지 않음), 파일이 다르면 새 세션", async () => {
    const server = setup();
    const f = [file("a.psmdl", "0123456789")];
    const a: Uploader = new Uploader(T, f, undefined, { ...fast, deps: { ...fast.deps, putChunk: async (...x: Parameters<typeof uploadApi.putChunk>): ReturnType<typeof uploadApi.putChunk> => (a.stop(), uploadApi.putChunk(...x)) } });
    expect(await a.run()).toBe(false); // 첫 청크 뒤 멈춤
    expect(a.progress).toMatchObject({ phase: "paused", sent: 4 });
    expect(localStorage.getItem(storeKey(STUDY, "MODEL_FOLDER"))).toContain(a.uploadId!);
    const b = new Uploader(T, f, undefined, fast); // 탭을 닫았다 같은 파일을 다시 고른 상황
    expect(await b.run()).toBe(true);
    expect(b.progress.resumed).toBe(true);
    expect(server.up.items).toHaveLength(1);
    expect(server.up.chunks.map((c) => c.offset)).toEqual([0, 4, 8]);
    // 다른 묶음 → 새 세션
    localStorage.clear();
    await new Uploader(T, [file("x.psmdl", "ab")], undefined, fast).run();
    await new Uploader(T, [file("y.psmdl", "ab")], undefined, fast).run();
    expect(server.up.items).toHaveLength(3);
  });

  it("서버가 세션을 닫았으면(CANCELED) 저장 세션을 버리고 새 세션", async () => {
    const server = setup();
    const f = [file("a.psmdl", "01234567")];
    const a: Uploader = new Uploader(T, f, undefined, { ...fast, deps: { ...fast.deps, putChunk: async (...x: Parameters<typeof uploadApi.putChunk>): ReturnType<typeof uploadApi.putChunk> => (a.stop(), uploadApi.putChunk(...x)) } });
    await a.run();
    server.up.items[0].state = "CANCELED";
    const b = new Uploader(T, f, undefined, fast);
    expect(await b.run()).toBe(true);
    expect(server.up.items).toHaveLength(2);
    expect(b.progress.resumed).toBe(false);
  });

  it("취소: 서버 세션 DELETE(CANCELED)·저장 세션 삭제, 취소 뒤 늦은 청크 응답은 화면을 되살리지 않는다", async () => {
    const server = setup();
    const phases: string[] = [];
    let release: () => void = () => undefined;
    const gate = new Promise<void>((r) => (release = r));
    const u = new Uploader(T, [file("a.psmdl", "01234567")], (p) => phases.push(p.phase), { ...fast, deps: { ...fast.deps, putChunk: async (...x) => (await gate, uploadApi.putChunk(...x)) } });
    const running = u.run();
    await vi.waitFor(() => expect(u.uploadId).toBeTruthy());
    await u.cancel();
    expect(server.up.items[0].state).toBe("CANCELED");
    expect(localStorage.getItem(storeKey(STUDY, "MODEL_FOLDER"))).toBeNull();
    release();
    await running; // 닫힌 세션에 늦게 도착한 청크는 409 → 오류가 되지만 화면(phase)은 canceled 로 남는다
    expect(phases[phases.length - 1]).toBe("canceled");
  });

  it("COMPLETED 세션 취소는 서버가 409 UPLOAD_CLOSED(입력 원본 보호)", async () => {
    setup();
    const u = new Uploader(T, [file("a.psmdl", "ab")], undefined, fast);
    await u.run();
    await u.complete();
    await expect(u.cancel()).rejects.toMatchObject({ status: 409, code: "UPLOAD_CLOSED" });
  });
});
