// 결과 3D 컨투어 순수 로직(geometry-view.md §13.4·§13.6): 프레임 Range 계산·디코딩(리틀엔디언, 변위 유무), 범례 범위,
// 색 매핑(NaN 회색), 변형 배율, 최근 N프레임 캐시, 대기 안내 단계·진행 상태 전이. three 미적재.
import { describe, expect, it } from "vitest";
import { applyDeform, contourView, decodeFrame, etaText, fmtSeconds, FrameCache, frameRange, legendRange, nextFrame, prevFrame, progressPercent, recordBytes, scalarMinMax, stepMarks, type ContourManifest } from "../stages/stage4/geomview/contour/contourCore";
import { fillColors, legendTicks, lutIndex, LUT, NAN_RGB } from "../stages/stage4/geomview/contour/colormap";
import { contourData } from "../mock/geomViewData";
import type { Contour3d } from "../api/types";

function manifest(n: number, hasDisp: boolean, list: ContourManifest["frames"]["list"]): ContourManifest {
  return {
    schema_version: 1, kind: "contour3d", status: "OK", mesh: { nodes: n },
    frames: { count: list.length, record_bytes: recordBytes(n, hasDisp), has_disp: hasDisp, list }, range: { min: 0, max: 10 },
  };
}

/** 프레임 우선 레코드 bin(리틀엔디언) */
function bin(frames: number[][], disp?: number[][][]): ArrayBuffer {
  const n = frames[0].length;
  const rb = recordBytes(n, !!disp);
  const buf = new ArrayBuffer(rb * frames.length);
  const dv = new DataView(buf);
  frames.forEach((f, i) => {
    f.forEach((v, k) => dv.setFloat32(i * rb + k * 4, v, true));
    disp?.[i].forEach((d, k) => d.forEach((x, q) => dv.setFloat32(i * rb + n * 4 + (k * 3 + q) * 4, x, true)));
  });
  return buf;
}

describe("프레임 Range·디코딩", () => {
  it("record_bytes = 4·N·(1+3·disp), Range(포함 끝) = i × record_bytes", () => {
    expect(recordBytes(100, false)).toBe(400);
    expect(recordBytes(100, true)).toBe(1600);
    const m = manifest(100, true, [{ i: 0, src: 0, time: 0, min: 0, max: 1 }, { i: 1, src: 4, time: 1, min: 0, max: 2 }]);
    expect(frameRange(m, 0)).toEqual([0, 1599]);
    expect(frameRange(m, 1)).toEqual([1600, 3199]);
  });

  it("스칼라·변위 디코딩(레코드 1개 / 전체 버퍼 오프셋), 짧으면 오류", () => {
    const b = bin(
      [
        [1, 2, NaN],
        [4, 5, 6],
      ],
      [
        [[0, 0, 1], [0, 0, 2], [0, 0, 3]],
        [[1, 0, 0], [2, 0, 0], [3, 0, 0]],
      ],
    );
    const f0 = decodeFrame(b.slice(0, recordBytes(3, true)), 3, true);
    expect(Array.from(f0.scalar.subarray(0, 2))).toEqual([1, 2]);
    expect(Number.isNaN(f0.scalar[2])).toBe(true);
    expect(Array.from(f0.disp!)).toEqual([0, 0, 1, 0, 0, 2, 0, 0, 3]);
    const f1 = decodeFrame(b, 3, true, recordBytes(3, true));
    expect(Array.from(f1.scalar)).toEqual([4, 5, 6]);
    expect(Array.from(f1.disp!.subarray(0, 3))).toEqual([1, 0, 0]);
    const s = decodeFrame(bin([[7, 8]]), 2, false);
    expect(Array.from(s.scalar)).toEqual([7, 8]);
    expect(s.disp).toBeNull();
    expect(() => decodeFrame(new ArrayBuffer(4), 3, false)).toThrow(/짧습니다/);
  });

  it("목 contour_frames.bin: 프레임 i 레코드의 min·max = manifest list[i]", () => {
    const d = contourData("PREDICT_H3D", { job_id: "j" });
    const m = d.manifest;
    expect(d.frames.byteLength).toBe(m.frames.count * m.frames.record_bytes);
    for (const i of [0, 7, m.frames.count - 1]) {
      const [a, b] = frameRange(m, i);
      const f = decodeFrame(d.frames.slice(a, b + 1).buffer, m.mesh.nodes, true);
      const mm = scalarMinMax(f.scalar)!;
      expect(mm[0]).toBeCloseTo(m.frames.list[i].min!, 3);
      expect(mm[1]).toBeCloseTo(m.frames.list[i].max!, 3);
    }
  });
});

describe("범례·색·변형", () => {
  const m = manifest(2, false, [{ i: 0, src: 0, time: 0, min: 2, max: 3 }, { i: 1, src: 1, time: 1, min: null, max: null }]);
  it("고정 = range, 프레임별 = list[i](null이면 고정)", () => {
    expect(legendRange(m, 0, "global")).toEqual([0, 10]);
    expect(legendRange(m, 0, "frame")).toEqual([2, 3]);
    expect(legendRange(m, 1, "frame")).toEqual([0, 10]);
    expect(legendRange({ ...m, range: { min: null, max: null } }, 1, "frame")).toBeNull();
  });
  it("NaN 제외 min·max, 전부 NaN이면 null", () => {
    expect(scalarMinMax([3, NaN, -1])).toEqual([-1, 3]);
    expect(scalarMinMax([NaN])).toBeNull();
  });
  it("색: min → 표 처음, max → 끝, NaN → 회색, 범위 0 → 가운데", () => {
    expect(lutIndex(0, 0, 10)).toBe(0);
    expect(lutIndex(10, 0, 10)).toBe(255);
    expect(lutIndex(99, 0, 10)).toBe(255);
    expect(lutIndex(NaN, 0, 10)).toBe(-1);
    expect(lutIndex(5, 5, 5)).toBe(128);
    const out = fillColors([0, NaN, 10], 0, 10, new Float32Array(9));
    expect(Array.from(out.subarray(0, 3))).toEqual(Array.from(LUT.subarray(0, 3)));
    expect(Array.from(out.subarray(3, 6))).toEqual(NAN_RGB.map((x) => Math.fround(x)));
    expect(Array.from(out.subarray(6, 9))).toEqual(Array.from(LUT.subarray(255 * 3, 256 * 3)));
    expect(legendTicks(0, 10, 3)).toEqual([10, 5, 0]);
    // three 정점 색용 = 같은 칸의 선형값(sRGB → linear, 더 작음)
    const lin = fillColors([10], 0, 10, new Float32Array(3), true);
    expect(lin[0]).toBeCloseTo(Math.fround(((LUT[765] + 0.055) / 1.055) ** 2.4), 5);
    expect(lin[0]).toBeLessThan(LUT[765]);
  });
  it("변형 = POSITION + 배율 × disp(배율 0·disp 없음 = 원위치, 비유한 변위 = 0)", () => {
    const base = new Float32Array([0, 0, 0, 1, 1, 1]);
    const disp = new Float32Array([0, 0, 1, NaN, 0, 2]);
    expect(Array.from(applyDeform(base, disp, 10, new Float32Array(6)))).toEqual([0, 0, 10, 1, 1, 21]);
    expect(Array.from(applyDeform(base, disp, 0, new Float32Array(6)))).toEqual([0, 0, 0, 1, 1, 1]);
    expect(Array.from(applyDeform(base, null, 5, new Float32Array(6)))).toEqual([0, 0, 0, 1, 1, 1]);
  });
  it("재생 반복·최근 N프레임 캐시", () => {
    expect(nextFrame(2, 3)).toBe(0);
    expect(prevFrame(0, 3)).toBe(2);
    const c = new FrameCache<number>(3);
    [0, 1, 2].forEach((i) => c.set(i, i));
    c.get(0); // 최근 사용
    c.set(3, 3);
    expect(c.keys().sort()).toEqual([0, 2, 3]);
    expect(c.has(1)).toBe(false);
  });
});

describe("대기 안내 진행 상태 전이(열 때 생성)", () => {
  const c = (x: Partial<Contour3d>) => ({ id: "c", status: "QUEUED", source_kind: "PREDICT_H3D", source_ref: {}, ...x }) as Contour3d;
  it("단계 스테퍼: 대기 → H3D 읽기 → 형상 → 프레임 변환 → 완료, 실패·취소는 그 단계 빨강", () => {
    expect(stepMarks("waiting")).toEqual(["active", "todo", "todo", "todo", "todo"]);
    expect(stepMarks("geometry")).toEqual(["done", "done", "active", "todo", "todo"]);
    expect(stepMarks("done")).toEqual(["done", "done", "done", "done", "done"]);
    expect(stepMarks("failed", "frames")).toEqual(["done", "done", "done", "failed", "todo"]);
    expect(stepMarks("canceled")).toEqual(["failed", "todo", "todo", "todo", "todo"]);
  });
  it("화면 상태: 생성 중·표시·결과 실패·작업 실패·취소·만료", () => {
    expect(contourView(null)).toBe("idle");
    expect(contourView(c({ status: "QUEUED" }))).toBe("waiting");
    expect(contourView(c({ status: "RUNNING" }))).toBe("waiting");
    expect(contourView(c({ status: "DONE", result_status: "OK" }))).toBe("ready");
    expect(contourView(c({ status: "DONE", result_status: "FAIL" }))).toBe("result_fail");
    expect(contourView(c({ status: "FAILED" }))).toBe("failed");
    expect(contourView(c({ status: "CANCELED" }))).toBe("canceled");
    expect(contourView(c({ status: "EXPIRED" }))).toBe("expired");
  });
  it("진행률(percent 없으면 단계 위치), 경과·예상 문구(없으면 '수 분')", () => {
    expect(progressPercent(c({ progress: { phase: "frames", phase_label: "프레임 변환", percent: 62, can_cancel: true } }))).toBe(62);
    expect(progressPercent(c({ progress: { phase: "geometry", phase_label: "형상", can_cancel: true } }))).toBe(50);
    expect(progressPercent(c({}))).toBeNull();
    expect(fmtSeconds(42)).toBe("42초");
    expect(fmtSeconds(65)).toBe("1분 05초");
    expect(etaText(c({ progress: { phase: "waiting", phase_label: "대기", can_cancel: true } }))).toBe("예상 시간 수 분");
    expect(etaText(c({ progress: { phase: "frames", phase_label: "", can_cancel: true, elapsed_s: 40, estimate_s: 100 } }))).toBe("예상 1분 40초 · 남은 약 1분 00초");
    expect(etaText(c({ progress: { phase: "frames", phase_label: "", can_cancel: true, elapsed_s: 120, estimate_s: 100 } }))).toContain("곧 끝납니다");
  });
});
