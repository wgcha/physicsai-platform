// v0.2.9 3차 통합: PREVIEW 레인 작업(ASM_MATCH·GEOM_PREVIEW)과 CONTOUR_3D의 화면 라벨·단계가 빠지면 대기열·작업 목록에 undefined가 뜬다.
import { describe, expect, it } from "vitest";
import { JOB_STAGE, JOB_TYPE_LABEL } from "../lib/format";
import { stepLabel } from "../lib/steps";
import { STEP_CHAINS } from "../mock/steps";
import { STAGE_LABEL } from "../mock/catalog";
import type { JobType } from "../api/types";

describe("작업 종류 라벨·단계 (undefined 방지)", () => {
  const types = Object.keys(JOB_TYPE_LABEL) as JobType[];

  it("ASM_MATCH·GEOM_PREVIEW·CONTOUR_3D 라벨과 단계가 있다", () => {
    expect(JOB_TYPE_LABEL.ASM_MATCH).toBe("조립 매칭");
    expect(JOB_TYPE_LABEL.GEOM_PREVIEW).toBe("형상 미리보기");
    expect(JOB_TYPE_LABEL.CONTOUR_3D).toBe("결과 3D 컨투어");
    expect(JOB_STAGE.ASM_MATCH).toBe(1);
    expect(JOB_STAGE.GEOM_PREVIEW).toBe(4);
  });

  it("모든 작업 종류가 라벨·단계·단계 표시·step 체인을 갖는다", () => {
    for (const t of types) {
      expect(JOB_TYPE_LABEL[t], t).toBeTruthy();
      expect(JOB_STAGE[t], t).toBeTypeOf("number");
      expect(STAGE_LABEL[t], t).toBeTruthy();
      expect(STEP_CHAINS[t]?.length, t).toBeGreaterThan(0);
    }
  });

  it("조립 매칭·형상 미리보기·3D 컨투어의 모든 step 키(AM_*·GV_*·C3_*)에 표시명이 있다", () => {
    for (const k of ["AM_PREP", "AM_PARTS", "AM_CHECK", "AM_REGISTER", "GV_PREP", "GV_RUN", "GV_REGISTER", "C3_PREP", "C3_EXTRACT", "C3_CONVERT", "C3_REGISTER"]) {
      expect(stepLabel(k), k).not.toBe(k);
    }
  });
});
