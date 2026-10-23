// v0.2.10 결과 3D 컨투어 현장 보정(contour3d-field, V-C3F-15 순수 로직): uint16 복원·NaN, schema 1·2 호환, 변위 없음 판정, 툴팁 자리수, 극값, LOD 상태기,
// 바이트 예산 캐시, 대체 사유 문구. three 미적재.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  applyDeformGather,
  ByteBudgetCache,
  decodeDispFor,
  decodeDispU16,
  decodeFrame,
  decodeScalarFor,
  decodeScalarU16,
  defaultDeformScale,
  DENIED_TEXT,
  dispRange,
  dispRecordBytes,
  extremeLabel,
  ALWAYS_FULL_KEY,
  featureOffText,
  fullLoadingText,
  loadAlwaysFull,
  saveAlwaysFull,
  fmtQuantized,
  frameExtremes,
  frameRange,
  gatherValues,
  isQuantized,
  legendRange,
  jobFailText,
  LodGate,
  LOD_SETTLE_MS,
  manifestHasDisp,
  NO_SOURCE_TEXT,
  requestReason,
  resultFailText,
  tooltipText,
  warningLines,
  WEBGL_TEXT,
  type LodLevel,
  type ContourManifest,
} from "../stages/stage4/geomview/contour/contourCore";
import { contourData } from "../mock/geomViewData";

const u16 = (vals: number[]) => new Uint16Array(vals).buffer;

describe("uint16 복원(C3F-5)", () => {
  it("v̂ = min + q·scale, 65535 = NaN, 오프셋(바이트) 지원", () => {
    const out = decodeScalarU16(u16([0, 1, 32767, 65534, 65535]), 5, 10, 0.5);
    expect(Array.from(out.slice(0, 4))).toEqual([10, 10.5, 10 + 32767 * 0.5, 10 + 65534 * 0.5]);
    expect(Number.isNaN(out[4])).toBe(true);
    const two = new Uint16Array([7, 7, 2, 4]).buffer; // 두 번째 레코드 = 바이트 4부터
    expect(Array.from(decodeScalarU16(two, 2, 0, 1, 4))).toEqual([2, 4]);
    expect(() => decodeScalarU16(u16([1, 2]), 3, 0, 1)).toThrow(/짧습니다/);
  });

  it("홀수 오프셋도 읽는다(정렬 폴백)", () => {
    const b = new Uint8Array(1 + 4);
    new DataView(b.buffer).setUint16(1, 3, true);
    new DataView(b.buffer).setUint16(3, 65535, true);
    const out = decodeScalarU16(b.buffer, 2, 1, 2, 1);
    expect(out[0]).toBe(7);
    expect(Number.isNaN(out[1])).toBe(true);
  });

  it("scale 0(상수 프레임)은 모두 min", () => {
    expect(Array.from(decodeScalarU16(u16([0, 0, 0]), 3, 4.5, 0))).toEqual([4.5, 4.5, 4.5]);
  });

  it("변위: 성분별 min + q·scale, 정점마다 dx,dy,dz", () => {
    const out = decodeDispU16(u16([0, 10, 100, 2, 20, 200]), 2, [1, 2, 3], [0, 0.5, 0.01]);
    expect(Array.from(out)).toEqual([1, 2 + 5, 3 + 1, 1, 2 + 10, 3 + 2]);
  });

  it("양자화 왕복 오차 ≤ (max−min)/131068 — 합성 값(NaN·inf 포함)", () => {
    const vals = Array.from({ length: 500 }, (_, k) => 400 * Math.sin(k / 17) + 3);
    const finite = vals.filter(Number.isFinite);
    const lo = Math.min(...finite);
    const hi = Math.max(...finite);
    const s = (hi - lo) / 65534;
    const q = vals.map((v) => Math.round((v - lo) / s));
    q.push(65535, 65535); // NaN·inf
    const back = decodeScalarU16(u16(q), q.length, lo, s);
    vals.forEach((v, k) => expect(Math.abs(back[k] - v)).toBeLessThanOrEqual((hi - lo) / 131068 + 1e-4));
    expect(Number.isNaN(back[500]) && Number.isNaN(back[501])).toBe(true);
  });
});

describe("schema 1·2 호환", () => {
  const v1 = contourData("PREDICT_H3D", { job_id: "j" }, { schema: 1 });
  const v2 = contourData("PREDICT_H3D", { job_id: "j" }, { schema: 2 });

  it("판정: schema 1 = float32 섞임 레코드, schema 2 = uint16q + 별도 변위", () => {
    expect(isQuantized(v1.manifest)).toBe(false);
    expect(isQuantized(v2.manifest)).toBe(true);
    const n = v2.manifest.mesh.nodes;
    expect(v1.manifest.frames.record_bytes).toBe(16 * n);
    expect(v2.manifest.frames.record_bytes).toBe(2 * n);
    expect(dispRecordBytes(v2.manifest)).toBe(6 * n);
    expect(dispRecordBytes(v1.manifest)).toBe(0);
    expect(v2.frames.byteLength).toBe(2 * n * v2.manifest.frames.count);
    expect(v2.disp!.byteLength).toBe(6 * n * v2.manifest.frames.count);
    expect(frameRange(v2.manifest, 3)).toEqual([6 * n, 8 * n - 1]);
    expect(dispRange(v2.manifest, 3)).toEqual([18 * n, 24 * n - 1]);
  });

  it("같은 원본: v2 복원값 = v1 float32 값(오차 ≤ (max−min)/131068), 변위도 일치", () => {
    const n = v1.manifest.mesh.nodes;
    for (const i of [0, 5, 23]) {
      const a = decodeFrame(v1.frames.buffer as ArrayBuffer, n, true, frameRange(v1.manifest, i)[0]);
      const b = decodeScalarFor(v2.manifest, i, v2.frames.buffer as ArrayBuffer, frameRange(v2.manifest, i)[0]);
      const f = v2.manifest.frames.list[i];
      const tol = ((f.max as number) - (f.min as number)) / 131068 + 1e-3;
      for (let k = 0; k < n; k += 7) expect(Math.abs(b[k] - a.scalar[k])).toBeLessThanOrEqual(tol);
      const d = decodeDispFor(v2.manifest, i, v2.disp!.buffer as ArrayBuffer, dispRange(v2.manifest, i)[0]);
      for (let k = 0; k < n; k += 11) expect(Math.abs(d[k * 3 + 2] - (a.disp as Float32Array)[k * 3 + 2])).toBeLessThanOrEqual(6 / 65535 + 1e-4);
    }
    // schema 1 manifest는 decodeScalarFor가 float32 레코드의 앞부분을 그대로 읽는다
    const x = decodeScalarFor(v1.manifest, 4, v1.frames.buffer as ArrayBuffer, frameRange(v1.manifest, 4)[0]);
    expect(Array.from(x.slice(0, 5))).toEqual(Array.from(decodeFrame(v1.frames.buffer as ArrayBuffer, n, true, frameRange(v1.manifest, 4)[0]).scalar.slice(0, 5)));
  });

  it("manifest 극값: min_v·max_v가 가리키는 값이 프레임 min·max(정확값)", () => {
    const n = v2.manifest.mesh.nodes;
    const i = 12;
    const f = v2.manifest.frames.list[i];
    const s = decodeScalarFor(v2.manifest, i, v2.frames.buffer as ArrayBuffer, frameRange(v2.manifest, i)[0]);
    expect(f.max_v).toBeLessThan(n);
    expect(Math.abs(s[f.max_v as number] - (f.max as number))).toBeLessThanOrEqual((f.scale as number) / 2 + 1e-3);
    expect(Math.abs(s[f.min_v as number] - (f.min as number))).toBeLessThanOrEqual((f.scale as number) / 2 + 1e-3);
  });

  it("변위 없음: has_disp·disp 판정과 기본 배율", () => {
    const none = contourData("PREDICT_H3D", { job_id: "j" }, { schema: 2, disp: false });
    expect(none.disp).toBeNull();
    expect(none.manifest.disp).toBeNull();
    expect(manifestHasDisp(none.manifest)).toBe(false);
    expect(defaultDeformScale(none.manifest)).toBe(0);
    expect(warningLines(none.manifest).map((w) => w.text)).toEqual(["변형 표시 없음 — 결과에 변위가 없습니다"]);
    expect(manifestHasDisp(v1.manifest)).toBe(true);
    expect(manifestHasDisp(v2.manifest)).toBe(true);
    expect(defaultDeformScale(v1.manifest)).toBe(1);
    expect(defaultDeformScale(v2.manifest)).toBe(1);
    expect(manifestHasDisp({ ...v1.manifest, frames: { ...v1.manifest.frames, has_disp: false } })).toBe(false);
  });

  it("기본 배율: 변위 레코드 > 2 MiB(N > 약 35만)면 0", () => {
    const big = { ...v2.manifest, mesh: { ...v2.manifest.mesh, nodes: 973060 }, disp: { ...v2.manifest.disp!, record_bytes: 6 * 973060 } };
    expect(defaultDeformScale(big)).toBe(0);
    const edge = { ...v2.manifest, disp: { ...v2.manifest.disp!, record_bytes: 2 * 1024 * 1024 } };
    expect(defaultDeformScale(edge)).toBe(1);
  });
});

describe("전부 NaN 프레임(서버: min·max·min_v·max_v null, scale 0.0)", () => {
  const m = {
    schema_version: 2, kind: "contour3d", status: "OK", mesh: { nodes: 3, compression: "none" },
    frames: { count: 2, record_bytes: 6, has_disp: false, dtype: "uint16q", nan_code: 65535, list: [
      { i: 0, src: 0, time: 0, min: null, max: null, scale: 0.0, min_v: null, max_v: null },
      { i: 1, src: 1, time: 1, min: 1, max: 3, scale: 2 / 65534, min_v: 0, max_v: 2 },
    ] },
    range: { min: 1, max: 3 },
  } as unknown as ContourManifest;

  it("복원은 모두 NaN, 극값 마커 없음, 프레임별 범례는 고정 범위로 대체", () => {
    const out = decodeScalarFor(m, 0, u16([65535, 65535, 65535]), 0);
    expect(Array.from(out).every(Number.isNaN)).toBe(true);
    expect(frameExtremes(m, 0)).toEqual([]);
    expect(legendRange(m, 0, "frame")).toEqual([1, 3]);
    expect(legendRange(m, 1, "frame")).toEqual([1, 3]);
    expect(tooltipText(5, out[0], m.frames.list[0].scale, "MPa")).toBe("노드 5 · 값 없음");
  });

  it("전체 범위도 null이면 범례 없음", () => {
    expect(legendRange({ ...m, range: { min: null, max: null } }, 0, "global")).toBeNull();
  });
});

describe("툴팁·극값 표시(§5.5)", () => {
  it("소수 자리 = max(0, −floor(log10 s)), 유효숫자 ≤ 6, 양자화 간격보다 정밀하지 않음", () => {
    expect(fmtQuantized(123.456789, 0.0061)).toBe("123.457"); // s=0.0061 → 3자리
    expect(fmtQuantized(123.456789, 0.0001)).toBe("123.457"); // 간격은 4자리지만 유효 6자리
    expect(fmtQuantized(412.3456, 0.01)).toBe("412.35");
    expect(fmtQuantized(412.3456, 5)).toBe("412"); // s ≥ 1 → 소수 0자리
    expect(fmtQuantized(0.0123456, 0.00001)).toBe("0.01235"); // 간격 5자리
    expect(fmtQuantized(0.0123456, 1e-9)).toBe("0.0123456"); // 간격은 9자리지만 유효 6자리(소수 7자리)
    expect(fmtQuantized(1234567.89, 0.001)).toBe("1234568");
    expect(fmtQuantized(Number.NaN, 0.1)).toBe("–");
  });

  it("s = 0이면 값을 그대로, scale이 없으면(schema 1) 유효 6자리", () => {
    expect(fmtQuantized(4.5, 0)).toBe("4.5");
    expect(fmtQuantized(3.14159265, null)).toBe("3.14159");
  });

  it("툴팁 문구: 노드 {id} · {v̂} {단위}, NaN은 값 없음", () => {
    expect(tooltipText(100006, 412.3456, 0.01, "MPa")).toBe("노드 100006 · 412.35 MPa");
    expect(tooltipText(100006, 5, 0, "")).toBe("노드 100006 · 5");
    expect(tooltipText(7, Number.NaN, 0.1, "MPa")).toBe("노드 7 · 값 없음");
  });

  it("극값: 프레임의 max_v·min_v와 정확값으로 라벨(노드 번호 모르면 생략), schema 1은 없음", () => {
    const m = contourData("PREDICT_H3D", { job_id: "j" }, { schema: 2 }).manifest;
    const e = frameExtremes(m, 10);
    expect(e.map((x) => x.kind)).toEqual(["max", "min"]);
    expect(e[0].value).toBe(m.frames.list[10].max);
    expect(extremeLabel(e[0], 100003, "MPa")).toBe(`최대 ${Number((m.frames.list[10].max as number).toPrecision(6))} MPa · 노드 100003`);
    expect(extremeLabel({ kind: "min", vertex: 1, value: 0.5, node: null, xyz: null }, null, "")).toBe("최소 0.5");
    expect(frameExtremes(contourData("PREDICT_H3D", { job_id: "j" }, { schema: 1 }).manifest, 3)).toEqual([]);
  });

  it("극값 좌표: manifest의 노드 ID·원 좌표(max_xyz 등)를 그대로, 필드가 없으면(예전 v2) null로 폴백", () => {
    const m = contourData("PREDICT_H3D", { job_id: "j" }, { schema: 2 }).manifest;
    const f = m.frames.list[4];
    const e = frameExtremes(m, 4);
    expect(e[0].node).toBe(f.max_node);
    expect(e[0].xyz).toEqual(f.max_xyz);
    expect(e[1].node).toBe(f.min_node);
    expect(e[1].xyz).toEqual(f.min_xyz);
    expect(e[0].xyz).toHaveLength(3);
    const old = contourData("PREDICT_H3D", { job_id: "j" }, { schema: 2, legacyExtremes: true }).manifest;
    expect(old.frames.list[4].max_xyz).toBeUndefined();
    expect(frameExtremes(old, 4).map((x) => [x.node, x.xyz])).toEqual([
      [null, null],
      [null, null],
    ]);
    const bad = { frames: { list: [{ i: 0, max: 1, max_v: 2, max_xyz: [1, 2] as unknown as [number, number, number] }] } } as unknown as ContourManifest;
    expect(frameExtremes(bad, 0)[0].xyz).toBeNull(); // 길이·값이 잘못되면 쓰지 않는다
  });

  it("경고 문구: DISP_DROPPED·COMPS_IGNORED, 접두 유무·문자열 배열 모두", () => {
    const m = { warnings: [{ code: "CONTOUR3D_DISP_DROPPED" }, "COMPS_IGNORED", { code: "CONTOUR3D_FACE_SKIPPED", message: "면 12개를 건너뜀" }, { code: "X" }] } as unknown as ContourManifest;
    expect(warningLines(m).map((w) => w.text)).toEqual(["변형 표시 없음 — 크기 또는 노드 수 상한으로 변위를 뺐습니다", "표시 부품 이름을 적용하지 못해 전체를 표시합니다", "면 12개를 건너뜀"]);
    expect(warningLines(null)).toEqual([]);
  });
});

describe("LOD ↔ 전체 해상도 상태기(§7.3, C3F-9)", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());
  const make = (hasLod: boolean) => {
    const seen: LodLevel[] = [];
    const g = new LodGate(hasLod, (l) => seen.push(l));
    return { g, seen };
  };

  it("LOD 없으면 늘 전체", () => {
    const { g, seen } = make(false);
    expect(g.level).toBe("full");
    g.start();
    g.end();
    vi.advanceTimersByTime(1000);
    expect(g.level).toBe("full");
    expect(seen).toEqual([]);
  });

  it("첫 표시 = LOD, 전체를 받으면 전체", () => {
    const { g, seen } = make(true);
    expect(g.level).toBe("lod");
    g.setFullReady(true);
    expect(g.level).toBe("full");
    expect(seen).toEqual(["full"]);
  });

  it("[항상 전체 해상도]: 전체를 받기 전엔 LOD, 받은 뒤엔 조작·재생 중에도 전체, 끄면 다시 조작 중 LOD", () => {
    const { g, seen } = make(true);
    g.setAlwaysFull(true);
    expect(g.level).toBe("lod");
    g.setFullReady(true);
    g.start();
    g.setPlaying(true);
    expect(g.level).toBe("full");
    expect(seen).toEqual(["full"]);
    g.setAlwaysFull(false);
    expect(g.level).toBe("lod");
  });

  it("조작 시작 → LOD, 조작 끝 + 250 ms 뒤 전체(그 안에 다시 시작하면 LOD 유지)", () => {
    const { g, seen } = make(true);
    g.setFullReady(true);
    g.start();
    expect(g.level).toBe("lod");
    g.end();
    vi.advanceTimersByTime(LOD_SETTLE_MS - 1);
    expect(g.level).toBe("lod");
    g.start(); // 휠을 이어서
    g.end();
    vi.advanceTimersByTime(LOD_SETTLE_MS - 1);
    expect(g.level).toBe("lod");
    vi.advanceTimersByTime(1);
    expect(g.level).toBe("full");
    expect(seen).toEqual(["full", "lod", "full"]);
  });

  it("전체를 아직 못 받았으면 조작이 끝나도 LOD 유지", () => {
    const { g } = make(true);
    g.start();
    g.end();
    vi.advanceTimersByTime(1000);
    expect(g.level).toBe("lod");
    g.setFullReady(true);
    expect(g.level).toBe("full");
  });

  it("재생 중에는 LOD, 정지 + 250 ms 뒤 전체", () => {
    const { g } = make(true);
    g.setFullReady(true);
    g.setPlaying(true);
    expect(g.level).toBe("lod");
    g.setPlaying(false);
    expect(g.level).toBe("lod");
    vi.advanceTimersByTime(LOD_SETTLE_MS);
    expect(g.level).toBe("full");
  });

  it("pulse(시점 연결로 움직임)는 끝을 모르므로 마지막 pulse 뒤 250 ms에 전체", () => {
    const { g } = make(true);
    g.setFullReady(true);
    g.pulse();
    expect(g.level).toBe("lod");
    vi.advanceTimersByTime(200);
    g.pulse();
    vi.advanceTimersByTime(200);
    expect(g.level).toBe("lod");
    vi.advanceTimersByTime(60);
    expect(g.level).toBe("full");
  });

  it("dispose 뒤에는 타이머가 알리지 않는다", () => {
    const { g, seen } = make(true);
    g.setFullReady(true);
    g.start();
    g.end();
    g.dispose();
    vi.advanceTimersByTime(1000);
    expect(seen).toEqual(["full", "lod"]);
  });
});

describe("LOD 값 모으기·바이트 예산 캐시", () => {
  it("LOD 값 = 전체 레코드에서 src로 그대로(보간 없음), 변형도 src로", () => {
    expect(Array.from(gatherValues([10, 11, 12, 13], Uint32Array.from([3, 0]), new Float32Array(2)))).toEqual([13, 10]);
    const base = new Float32Array([0, 0, 0, 1, 1, 1]);
    const disp = new Float32Array([0, 0, 1, 0, 0, 2, 0, 0, 3]); // 원 정점 3개
    expect(Array.from(applyDeformGather(base, disp, 2, Uint32Array.from([2, 1]), new Float32Array(6)))).toEqual([0, 0, 6, 1, 1, 5]);
    expect(Array.from(applyDeformGather(base, disp, 0, Uint32Array.from([2, 1]), new Float32Array(6)))).toEqual([0, 0, 0, 1, 1, 1]);
  });

  it("예산을 넘으면 오래된 것부터 지우되 최소 2개는 남긴다, get은 최근으로 갱신", () => {
    const c = new ByteBudgetCache<Float32Array>(100); // 한 항목 40 B
    const f = () => new Float32Array(10);
    c.set(0, f());
    c.set(1, f());
    expect(c.keys()).toEqual([0, 1]);
    c.set(2, f()); // 120 B > 100 → 0 제거
    expect(c.keys()).toEqual([1, 2]);
    c.get(1);
    c.set(3, f());
    expect(c.keys()).toEqual([1, 3]);
    expect(c.bytes).toBe(80);
    const big = new ByteBudgetCache<Float32Array>(10); // 항목 하나가 예산보다 커도 최소 2개
    big.set(0, f());
    big.set(1, f());
    big.set(2, f());
    expect(big.keys()).toEqual([1, 2]);
    c.clear();
    expect(c.bytes).toBe(0);
  });
});

describe("대체 사유 문구(§12)", () => {
  const c = (o: Record<string, unknown>) => ({ message_ko: null, code: null, nodes: null, display: null, ...o }) as Parameters<typeof resultFailText>[0];
  const man = (o: Partial<ContourManifest>) => ({ schema_version: 2, kind: "contour3d", status: "FAIL", mesh: { nodes: 0 }, frames: { count: 0, record_bytes: 0, has_disp: false, list: [] }, range: { min: null, max: null }, ...o }) as ContourManifest;

  it("기능 꺼짐: missing 첫 키로 문구", () => {
    expect(featureOffText(["contour3d.enabled", "x"])).toBe("3D 꺼짐 — 관리자 설정 contour3d.enabled");
    expect(featureOffText(["resources.contour_extract_tcl"])).toBe("3D 꺼짐 — 추출 TCL 없음(resources.contour_extract_tcl)");
    expect(featureOffText(["commands.contour_extract"])).toBe("3D 꺼짐 — HyperView 경로 미설정(commands.contour_extract)");
    expect(featureOffText([])).toBe("3D 꺼짐 — 관리자 설정 contour3d.enabled");
  });

  it("고정 문구: WebGL 불가·원본 없음·member", () => {
    expect(WEBGL_TEXT).toBe("3D 불가 — 이 브라우저에서 WebGL2를 쓸 수 없습니다");
    expect(NO_SOURCE_TEXT).toBe("3D 없음 — 결과 h3d가 없습니다");
    expect(DENIED_TEXT).toBe("3D 미생성 — 처음 생성은 power 권한이 필요합니다");
  });

  it("작업 FAILED: 3D 생성 실패 — {message_ko} ({code})", () => {
    expect(jobFailText({ message_ko: "H3D 읽기 도구가 종료되었습니다", code: "CONTOUR3D_JOB_FAILED" })).toBe("3D 생성 실패 — H3D 읽기 도구가 종료되었습니다 (CONTOUR3D_JOB_FAILED)");
  });

  it("TOO_LARGE·노드: 천 단위 구분, 부품 범위가 있을 때만 '부품 이름으로' 문구", () => {
    const m = man({ code: "CONTOUR3D_TOO_LARGE", limits: { nodes: 973060, max_nodes: 300000 } });
    expect(resultFailText(c({ code: "CONTOUR3D_TOO_LARGE" }), m)).toBe("3D 생략 — 외부 면 노드 973,060개 > 상한 300,000. 관리자에게 상한(contour3d.max_nodes) 조정을 요청하세요");
    const withComps = man({ code: "CONTOUR3D_TOO_LARGE", limits: { nodes: 973060, max_nodes: 300000 }, scope: { comps: ["CUSHION"], applied: false } });
    expect(resultFailText(c({ code: "CONTOUR3D_TOO_LARGE" }), withComps)).toBe("3D 생략 — 외부 면 노드 973,060개 > 상한 300,000. 부품 이름으로 범위를 줄이거나 관리자에게 상한(contour3d.max_nodes) 조정을 요청하세요");
  });

  it("TOO_LARGE·노드: API reason.comps_applicable(쿠션 입력이 아님)이 있으면 manifest scope보다 우선", () => {
    const m = man({ code: "CONTOUR3D_TOO_LARGE", limits: { nodes: 973060, max_nodes: 300000 }, scope: { comps: [], comps_applicable: false, applied: false } });
    const reason = (comps_applicable: boolean) => ({ kind: "nodes", comps_applicable }) as never;
    expect(resultFailText(c({ code: "CONTOUR3D_TOO_LARGE", reason: reason(true) }), m)).toContain("부품 이름으로 범위를 줄이거나");
    expect(resultFailText(c({ code: "CONTOUR3D_TOO_LARGE", reason: reason(false) }), m)).not.toContain("부품 이름으로");
    // reason이 없으면 manifest scope.comps_applicable
    expect(resultFailText(c({ code: "CONTOUR3D_TOO_LARGE" }), man({ ...m, scope: { comps: ["A"], comps_applicable: true } }))).toContain("부품 이름으로");
  });

  it("TOO_LARGE·형상·프레임·manifest 없음", () => {
    const glb = man({ limits: { nodes: 1, max_nodes: 2, glb_bytes: 73400320, max_glb_bytes: 67108864 } });
    expect(resultFailText(c({ code: "CONTOUR3D_TOO_LARGE" }), glb)).toBe("3D 생략 — 형상 70.0 MB > 상한 64.0 MB(contour3d.max_glb_bytes), 관리자에게 조정을 요청하세요");
    const fr = man({ limits: { nodes: 1, max_nodes: 2, glb_bytes: 1, max_glb_bytes: 2 } });
    expect(resultFailText(c({ code: "CONTOUR3D_TOO_LARGE" }), fr)).toBe("3D 생략 — 프레임 2개도 크기 상한(contour3d.max_bin_bytes)을 넘습니다");
    expect(resultFailText(c({ code: "CONTOUR3D_TOO_LARGE", message_ko: "상한 초과" }), null)).toBe("3D 생략 — 상한 초과");
    // 노드 수는 응답(nodes)으로도 보강
    expect(resultFailText(c({ code: "CONTOUR3D_TOO_LARGE", nodes: 2350000 }), man({ limits: { max_nodes: 2000000 } }))).toContain("2,350,000개 > 상한 2,000,000");
  });

  it("값 없음은 필드 이름을, 그 밖은 message_ko", () => {
    expect(resultFailText(c({ code: "CONTOUR3D_FIELD_EMPTY", display: { field: "Stress" } }), null)).toBe("3D 생략 — 선택한 결과 값이 없습니다(Stress)");
    expect(resultFailText(c({ code: "CONTOUR3D_TIMEOUT", message_ko: "시간 초과" }), null)).toBe("3D 생략 — 시간 초과");
  });

  it("요청 단계: 403 → member, 409 NOT_CONFIGURED → 기능 꺼짐(응답 missing), 409 PREREQUISITE_MISSING → 원본 없음", () => {
    const base = { c: null, denied: false, error: null };
    expect(requestReason({ ...base, denied: true })).toBe(DENIED_TEXT);
    expect(requestReason({ ...base, error: "x", errInfo: { status: 409, code: "CONTOUR3D_NOT_CONFIGURED", missing: ["resources.contour_extract_tcl"] } })).toBe("3D 꺼짐 — 추출 TCL 없음(resources.contour_extract_tcl)");
    expect(requestReason({ ...base, error: "x", errInfo: { status: 409, code: "PREREQUISITE_MISSING", missing: [] } })).toBe(NO_SOURCE_TEXT);
    expect(requestReason({ ...base, error: "서버에 연결할 수 없습니다.", errInfo: null })).toBe("3D 컨투어를 요청하지 못했습니다 — 서버에 연결할 수 없습니다.");
    expect(requestReason(base)).toBeNull();
  });
});

describe("[항상 전체 해상도] 설정 저장·진행 문구(§7.3)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("localStorage에 저장·복원, 끄면 키 삭제", () => {
    expect(loadAlwaysFull()).toBe(false);
    saveAlwaysFull(true);
    expect(localStorage.getItem(ALWAYS_FULL_KEY)).toBe("1");
    expect(loadAlwaysFull()).toBe(true);
    saveAlwaysFull(false);
    expect(localStorage.getItem(ALWAYS_FULL_KEY)).toBeNull();
  });

  it("저장소가 막혀도(throw) 예외 없이 끔으로 동작", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("denied");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("denied");
    });
    expect(loadAlwaysFull()).toBe(false);
    expect(() => saveAlwaysFull(true)).not.toThrow();
  });

  it("받는 중 문구에 {p}%(0~100 고정), 총량을 모르면 …", () => {
    expect(fullLoadingText(0)).toBe("전체 해상도 받는 중 0%");
    expect(fullLoadingText(42.9)).toBe("전체 해상도 받는 중 42%");
    expect(fullLoadingText(250)).toBe("전체 해상도 받는 중 100%");
    expect(fullLoadingText(null)).toBe("전체 해상도 받는 중…");
  });
});
