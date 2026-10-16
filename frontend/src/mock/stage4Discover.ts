// phase3 §13 S8: ④ 파라미터 세트 "프로젝트 폴더에서 찾기" 목 — 경로 이름으로 시나리오 선택.
// "multi" = tpl·조립 폴더 후보 여러 개, "empty" = 하나도 없음, "cushion_only"·"meshonly" = 조립 폴더 0개(S9 mesh_only),
// 그 밖 = 후보 1개씩(tpl에서 파라미터 생성).
import type { ParamSet, ParamSetDiscover } from "../api/types";
import { inspectPath } from "./studies";
import { err, type MockResp } from "./route";
import { PARAMS } from "./data";

const TPL = { rel: "simlab_parametered_mesh.tpl", name: "simlab_parametered_mesh.tpl", parameter_count: PARAMS.length, cad_ref: "./cushion_base.x_t" };
const TPL2 = { rel: "TEMAPLATE_simlab_parametered_mesh.tpl", name: "TEMAPLATE_simlab_parametered_mesh.tpl", parameter_count: PARAMS.length, cad_ref: "C:\\DATA\\01_CAD\\cushion_base.x_t" };
const ASSEM = { rel: "RADIOSS_ASSEM", starter: "cushion_0000.rad", has_eps_mesh: true, has_renum_csv: true, file_count: 6 };
/** S9 §14.4: 조립 폴더 0개 → mesh_only 안내 */
const MESH_ONLY_NOTE = { code: "MESH_ONLY", message: "조립 폴더 없음 — m1 메시로 바로 예측합니다" };
const ASSEM2 = { rel: "case_B/radioss", starter: "cushion_b_0000.rad", has_eps_mesh: false, has_renum_csv: false, file_count: 3 };

export function discover(path: string, tpl?: string | null): MockResp {
  const chk = inspectPath("PARAM_SET", path);
  if (chk.status !== 200) return chk;
  const base: ParamSetDiscover = {
    path, tpl: [], selected_tpl: null, cad: [], radioss_assem: [], parameters_source: null, parameters_file: null,
    parameters: [], samples: null, responses: null, problems: [], notes: [], truncated: false, scanned: 42,
  };
  if (/empty/i.test(path))
    return { status: 200, body: { ...base, problems: [
      { code: "TPL_NOT_FOUND", message: "{parameter(…)} 블록이 있는 SimLab tpl(*.tpl)을 찾지 못했습니다" },
    ], notes: [MESH_ONLY_NOTE] } };
  const multi = /multi/i.test(path);
  const meshOnly = /cushion_only|meshonly/i.test(path);
  const tpls = multi ? [TPL, TPL2] : [TPL];
  const sel = tpls.find((t) => t.rel === tpl) ?? (tpls.length === 1 ? tpls[0] : null);
  const out: ParamSetDiscover = {
    ...base, tpl: tpls, selected_tpl: sel?.rel ?? null, radioss_assem: multi ? [ASSEM, ASSEM2] : meshOnly ? [] : [ASSEM],
    notes: [...(multi && !sel ? [{ code: "TPL_CHOICE_REQUIRED", message: "tpl 후보가 2개입니다 — 하나를 고르세요" }] : []), ...(meshOnly ? [MESH_ONLY_NOTE] : [])],
  };
  if (sel) {
    out.cad = multi ? [{ rel: "01_CAD/cushion_base.x_t", name: "cushion_base.x_t" }, { rel: "old/cushion_base.x_t", name: "cushion_base.x_t" }]
      : [{ rel: "01_CAD/cushion_base.x_t", name: "cushion_base.x_t" }];
    out.parameters_source = "tpl";
    out.parameters = PARAMS.map((p) => ({ ...p, unit: "" }));
  }
  return { status: 200, body: out };
}

/** POST param-sets {mode:"discover"} — 후보가 여러 개인데 고르지 않았으면 422. S9: radioss_assem 명시 null·후보 0개 = mesh_only */
export function registerDiscovered(path: string, choice: Record<string, string | null | undefined> | undefined): MockResp | (ParamSetDiscover & { chosen_assem: string | null }) {
  const r = discover(path, choice?.tpl);
  if (r.status !== 200) return r;
  const d = r.body as ParamSetDiscover;
  if (d.problems.length) return err(422, "PARAM_SET_INVALID", "프로젝트 폴더에서 파라미터 세트를 구성할 수 없습니다");
  const need = (list: { rel: string }[], v: string | null | undefined) => (v ? list.some((x) => x.rel === v) : list.length === 1);
  const assemNull = !!choice && "radioss_assem" in choice && choice.radioss_assem === null;
  const assemOk = assemNull || d.radioss_assem.length === 0 || need(d.radioss_assem, choice?.radioss_assem);
  if (!d.selected_tpl || !need(d.cad, choice?.cad) || !assemOk) return err(422, "PARAM_SET_INVALID", "후보 중 하나를 고르세요");
  const chosen = assemNull || d.radioss_assem.length === 0 ? null : choice?.radioss_assem || d.radioss_assem[0].rel;
  return { ...d, chosen_assem: chosen };
}

export function discoveredParams(d: ParamSetDiscover & { chosen_assem: string | null }): Pick<ParamSet, "parameters" | "sample_count" | "sample_has_measured" | "responses" | "input_kind" | "assem_rel" | "starter_name"> {
  const a = d.radioss_assem.find((x) => x.rel === d.chosen_assem);
  return {
    parameters: d.parameters, sample_count: 0, sample_has_measured: false, responses: [],
    input_kind: a ? "assembly" : "mesh_only", assem_rel: a ? "radioss_assem" : null, starter_name: a?.starter ?? null,
  };
}
