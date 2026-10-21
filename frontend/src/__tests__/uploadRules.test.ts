// upload-report.md §3.1·§5(V-UP-3·4·12): 미리 검사 — 이름 규칙(공백·괄호 등)·패턴 제외·항상 거부·모양·대소문자 중복.
import { describe, expect, it } from "vitest";
import type { UploadConfig } from "../api/uploads";
import { matchesAny, nameProblem, precheck, relFromFile, relProblem, rootName, sessionName } from "../components/upload/uploadRules";

const cfg = {
  enabled: true, chunk_size: 16 * 1024 ** 2, max_file_bytes: 1, max_upload_bytes: 1, max_files: 20000, max_concurrent_per_user: 2, free_bytes: null,
  always_denied: ["*.pscfg", "*.exe", "*.part"],
  purposes: {
    MODEL_FOLDER: { patterns: ["*.psmdl", "*.log", "*.json"], mode: "dir" },
    CAD_FILE: { patterns: ["*.prt"], mode: "file", engine_patterns: { native: ["*.stp", "*.step"], altair: ["*.prt"] } },
    RESULT_FOLDER: { patterns: ["*.h3d", "*t01", "*.csv"], mode: "dir" },
  },
} as unknown as UploadConfig;
const it_ = (rel: string, size = 1) => ({ file: new File(["x".repeat(size)], rel.split("/").pop()!), rel });

describe("업로드 미리 검사", () => {
  it("이름 규칙: 공백·괄호·cmd 메타문자·; , = '·제어문자·끝 점/공백·예약 이름은 거부, 한글·영숫자·_-. 는 허용", () => {
    for (const bad of ["model (1).h3d", "a b.rad", "a&b", "a;b", "a,b", "a=b", "it's", "a%b", "a!b", "a^b", 'a"b', "a|b", "a<b", "con", "nul.txt", "x.", "x ", "a:b", "탭\t.rad", "a b"]) expect(nameProblem(bad), bad).not.toBeNull();
    for (const ok of ["model_v3-final.h3d", "쿠션_해석.psmdl", "A001.k", "x.y.z", "*T01".replace("*", "run")]) expect(nameProblem(ok), ok).toBeNull();
    expect(nameProblem("a (1).h3d")).toContain("공백");
    expect(nameProblem("(a).h3d")).toContain("(");
    expect(relProblem("sub dir/ok.psmdl")).toContain("폴더 이름");
    expect(relProblem("_backup/x.log")).toContain("_backup");
    expect(relProblem(".hidden/x.log")).not.toBeNull();
    expect(relProblem("a".repeat(401))).not.toBeNull();
  });

  it("glob 패턴(대소문자 무시, 확장자 없는 *T01 포함)", () => {
    expect(matchesAny("Run_A.H3D", ["*.h3d"])).toBe(true);
    expect(matchesAny("RUNT01", ["*t01"])).toBe(true);
    expect(matchesAny("run.A001", ["*.h3d", "*t01"])).toBe(false);
    expect(matchesAny("a.rad.txt", ["*.rad"])).toBe(false);
  });

  it("패턴 밖·항상 거부(pscfg)는 '제외'(위반 아님), 이름 위반은 bad, 나머지는 올릴 파일", () => {
    const r = precheck([it_("m.psmdl", 5), it_("m.pscfg"), it_("notes.docx"), it_("train log.log"), it_("sub/ok.log", 3), it_("sub/OK.log")], cfg, "MODEL_FOLDER");
    expect(r.ok.map((x) => x.rel)).toEqual(["m.psmdl", "sub/ok.log"]);
    expect(r.excluded).toEqual([
      { rel: "m.pscfg", reason: "pscfg(pickle)는 올릴 수 없습니다" },
      { rel: "notes.docx", reason: "이 용도에서 쓰지 않는 파일" },
    ]);
    expect(r.bad.map((b) => b.rel)).toEqual(["train log.log", "sub/OK.log"]); // 공백 위반, 대소문자만 다른 중복
    expect(r.bytes).toBe(8);
  });

  it("결과 폴더: *.A001 애니메이션은 자동 제외, 확장자 없는 T01 은 통과", () => {
    const r = precheck([it_("r1/ANIM.h3d"), it_("r1/run.A001"), it_("r1/RUNT01"), it_("r1/out.csv")], cfg, "RESULT_FOLDER");
    expect(r.ok.map((x) => x.rel)).toEqual(["r1/ANIM.h3d", "r1/RUNT01", "r1/out.csv"]);
    expect(r.excluded.map((x) => x.rel)).toEqual(["r1/run.A001"]);
    expect(r.bad).toEqual([]);
  });

  it("CAD 는 engine 별 패턴과 파일 1개(폴더 성분 없음) 모양", () => {
    expect(precheck([it_("base.step")], cfg, "CAD_FILE", "native").ok).toHaveLength(1);
    expect(precheck([it_("base.step")], cfg, "CAD_FILE", "altair").shape).toBe("올릴 수 있는 파일이 없습니다");
    expect(precheck([it_("base.prt")], cfg, "CAD_FILE", "altair").ok).toHaveLength(1);
    expect(precheck([it_("a.stp"), it_("b.stp")], cfg, "CAD_FILE", "native").shape).toBe("이 용도는 파일 1개만 올릴 수 있습니다");
    expect(precheck([it_("d/a.stp")], cfg, "CAD_FILE", "native").shape).toBe("이 용도는 파일 1개만 올릴 수 있습니다");
  });

  it("폴더 선택 상대경로: 선택 폴더 이름을 떼고, 세션 이름은 안전 문자만", () => {
    const f = new File(["x"], "a.log");
    Object.defineProperty(f, "webkitRelativePath", { value: "my model/sub/a.log" });
    expect(relFromFile(f)).toBe("sub/a.log");
    expect(rootName(f)).toBe("my model");
    expect(relFromFile(new File(["x"], "b.log"))).toBe("b.log");
    expect(sessionName("my model (1)", undefined)).toBe("my_model_1");
    expect(sessionName(null, "base.step")).toBe("base");
    expect(sessionName("***", undefined)).toBe("upload");
  });
});
