// native-vars.md §6 목: GET·PUT /param-sets/{id}/variables(리비전·409 충돌·422 problems) + ⑥·④ 일괄의 `vars{add,exclude}` 처리(유효 변수·var_rows·경고).
// 학습 범위는 모델을 고르면 피처 기본 범위로 채운다(CUSH_L_POCKET_D_1만 모름) — 목은 서버 규칙의 핵심만 흉내(막지 않고 경고).
import type { NativeVarPoolRow, NativeVars, ParamSet, VarNote, VarRow } from "../api/types";
import { isPositionType } from "../lib/geometry";
import { NOTE_TEXT, exceedsFeasibleRange, exceedsTrain } from "../lib/nativeVars";
import { err, needPower, ok, type MockResp, type Route } from "./route";
import type { MockServer } from "./server";

interface Rev {
  revision: number;
  saved_at: string;
  saved_by_name: string;
  items: { name: string; min: number; max: number }[];
}
const REVS = new WeakMap<MockServer, Map<string, Rev[]>>();
const revsOf = (srv: MockServer, id: string): Rev[] => {
  let m = REVS.get(srv);
  if (!m) REVS.set(srv, (m = new Map()));
  if (!m.has(id)) m.set(id, []);
  return m.get(id)!;
};
const currentRevision = (srv: MockServer, id: string) => (revsOf(srv, id).slice(-1)[0]?.revision ?? 0);
const UNKNOWN_TRAIN = new Set(["CUSH_L_POCKET_D_1"]);
const hasModel = (srv: MockServer, modelId: string | null | undefined) => !!modelId && srv.models.some((m) => m.id === modelId);

/** 풀 = 세트 피처 파일 전체(목: 피처 목록) */
export function poolOf(srv: MockServer, ps: ParamSet, modelId?: string | null): NativeVarPoolRow[] {
  const rec = srv.geom.get(ps.id);
  const withTrain = hasModel(srv, modelId);
  return (rec?.features ?? []).map((f) => ({
    name: f.name, type: f.type, body: f.body, nominal: f.nominal ?? 0, unit: f.unit ?? "mm", position: isPositionType(f.type),
    default_range: { min: f.min ?? 0, max: f.max ?? 0 },
    feasible: f.feasible ? { min: f.feasible.min ?? null, max: f.feasible.max ?? null, source: f.feasible.source ?? "estimate" } : null,
    ref_locked: !!f.ref_locked, group: f.group ?? null,
    train: withTrain && !UNKNOWN_TRAIN.has(f.name) ? { min: f.min ?? 0, max: f.max ?? 0 } : null,
  }));
}

const setRows = (ps: ParamSet) => ps.parameters.filter((p) => p.source !== "prop");

function varsOut(srv: MockServer, ps: ParamSet, modelId: string | null, revision?: number | null): MockResp {
  const pool = poolOf(srv, ps, modelId);
  const revs = revsOf(srv, ps.id);
  const multi = !!srv.geom.get(ps.id)?.map;
  let variables = pool.filter((p) => setRows(ps).some((r) => r.name === p.name)).map((p) => {
    const r = setRows(ps).find((x) => x.name === p.name)!;
    return { name: p.name, min: r.min, max: r.max };
  });
  if (revision != null) {
    const rev = revs.find((r) => r.revision === revision);
    if (!rev && !(revision === 0 && !revs.length)) return err(404, "NATIVE_VARS_REVISION_NOT_FOUND", `변수 정의 리비전 ${revision}을(를) 찾을 수 없습니다`);
    if (rev) variables = rev.items;
  }
  const notes: VarNote[] = modelId && !hasModel(srv, modelId) ? [{ code: "TRAIN_RANGE_UNKNOWN", message: NOTE_TEXT.TRAIN_RANGE_UNKNOWN }] : [];
  if (modelId && hasModel(srv, modelId) && pool.some((p) => !p.train)) notes.push({ code: "TRAIN_RANGE_UNMATCHED", message: NOTE_TEXT.TRAIN_RANGE_UNMATCHED });
  const body: NativeVars = {
    revision: currentRevision(srv, ps.id), features_sha256: "mock", editable: !multi,
    reason: multi ? "다중 baseline 템플릿은 변수 추가·제외를 아직 지원하지 않습니다" : null,
    variables, pool, stale_names: [],
    train_source: hasModel(srv, modelId) ? { model_id: modelId, dataset_id: "ds-mock", doe_ids: ["doe-mock"] } : null,
    notes, warnings: [],
    history: [...revs].reverse().slice(0, 20).map((r) => ({ revision: r.revision, saved_at: r.saved_at, saved_by_name: r.saved_by_name, count: r.items.length })),
  };
  return ok(body);
}

function put(srv: MockServer, ps: ParamSet, body: Record<string, unknown>): MockResp {
  const s = srv.studies.find((x) => x.id === ps.study_id)!;
  const deny = needPower(srv, s.project_id);
  if (deny) return deny;
  if (srv.geom.get(ps.id)?.map) return err(409, "NATIVE_VARS_MULTI_UNSUPPORTED", "다중 baseline 템플릿은 변수 추가·제외를 아직 지원하지 않습니다");
  if (Number(body.base_revision) !== currentRevision(srv, ps.id)) return err(409, "NATIVE_VARS_CONFLICT", "다른 사용자가 먼저 저장했습니다 — 새로 불러온 뒤 다시 저장하세요");
  const items = (body.variables ?? []) as { name: string; min: number; max: number }[];
  const pool = poolOf(srv, ps, null);
  const problems: { code: string; name?: string; message: string }[] = [];
  const seen = new Set<string>();
  for (const it of items) {
    if (!pool.some((p) => p.name === it.name)) problems.push({ code: "VAR_UNKNOWN", name: it.name, message: `'${it.name}'은 이 템플릿의 형상 변수가 아닙니다` });
    else if (seen.has(it.name)) problems.push({ code: "VAR_DUPLICATE", name: it.name, message: `'${it.name}'이(가) 중복되었습니다` });
    else if (!Number.isFinite(it.min) || !Number.isFinite(it.max) || it.min > it.max) problems.push({ code: "VAR_RANGE_INVALID", name: it.name, message: "하한·상한은 유한한 숫자이고 하한 ≤ 상한이어야 합니다" });
    seen.add(it.name);
  }
  const props = ps.parameters.filter((p) => p.source === "prop");
  if (!items.length && !props.length) problems.push({ code: "VARS_EMPTY", message: "변수를 하나 이상 고르세요" });
  if (problems.length) return err(422, "NATIVE_VARS_INVALID", "변수 정의가 올바르지 않습니다", { problems });
  const revs = revsOf(srv, ps.id);
  if (!revs.length) revs.push({ revision: 0, saved_at: ps.registered_at, saved_by_name: "등록", items: setRows(ps).map((r) => ({ name: r.name, min: r.min, max: r.max })) });
  const ordered = pool.filter((p) => seen.has(p.name)).map((p) => items.find((i) => i.name === p.name)!);
  revs.push({ revision: revs.length, saved_at: new Date().toISOString(), saved_by_name: srv.me?.display_name ?? "김연구", items: ordered });
  ps.parameters = [
    ...ordered.map((i) => {
      const p = pool.find((x) => x.name === i.name)!;
      return { name: i.name, nominal: p.nominal, min: i.min, max: i.max, unit: p.unit };
    }),
    ...props,
  ];
  if (ps.native) ps.native = { ...ps.native, vars_revision: currentRevision(srv, ps.id), vars_count: ordered.length };
  const out = varsOut(srv, ps, null);
  const v = out.body as NativeVars;
  const warnings: VarNote[] = [];
  for (const i of ordered) {
    const p = pool.find((x) => x.name === i.name)!;
    if (exceedsFeasibleRange(i.min, i.max, p.feasible)) warnings.push({ code: "VAR_OUT_OF_FEASIBLE", name: i.name, message: `'${i.name}' ${NOTE_TEXT.VAR_OUT_OF_FEASIBLE}` });
    if (p.ref_locked) warnings.push({ code: "VAR_REF_LOCKED", name: i.name, message: `'${i.name}' ${NOTE_TEXT.VAR_REF_LOCKED}` });
  }
  return ok({ ...v, warnings });
}

export const nativeVarsRoutes: Route = (srv, { method, seg, query, body }) => {
  if (seg[0] !== "param-sets" || seg[2] !== "variables" || seg.length !== 3) return null;
  const ps = srv.paramSets.find((p) => p.id === seg[1]);
  if (!ps) return err(404, "NOT_FOUND", "템플릿을 찾을 수 없습니다.");
  if (ps.engine !== "native") return err(422, "NATIVE_VARS_UNSUPPORTED", "변수 추가·제외는 Native 템플릿에서만 쓸 수 있습니다");
  if (method === "GET") {
    const rev = query.get("revision");
    return varsOut(srv, ps, query.get("model_id"), rev == null || rev === "" ? null : Number(rev));
  }
  if (method === "PUT") return put(srv, ps, body ?? {});
  return null;
};

// ------------------------------------------------------------------ ⑥·④ 일괄: vars{add,exclude}

export interface RunVars {
  ps: ParamSet;
  rows: VarRow[];
  excluded: string[];
  /** 그 자리 편집 여부 */
  edited: boolean;
}

/** 유효 변수 = (세트 정의 − exclude) + add. Altair면 NATIVE_VARS_UNSUPPORTED, 잘못된 이름이면 problem 문구 */
export function runVars(srv: MockServer, ps: ParamSet, vars: { add?: string[] | null; exclude?: string[] | null } | null | undefined, modelId?: string | null): { error: string | null; out: RunVars } {
  const add = vars?.add ?? [];
  const exclude = vars?.exclude ?? [];
  const pool = poolOf(srv, ps, modelId);
  let error: string | null = null;
  if (ps.engine !== "native" && (add.length || exclude.length)) error = "NATIVE_VARS_UNSUPPORTED";
  const set = ps.parameters; // 쉘 두께 PROP 행도 세트 정의(제외·범위 변경 대상)
  for (const n of add) if (!pool.some((p) => p.name === n) || set.some((r) => r.name === n)) error ??= "vars.add";
  for (const n of exclude) if (!set.some((r) => r.name === n)) error ??= "vars.exclude";
  const eff = [
    ...set.filter((r) => !exclude.includes(r.name)).map((r) => ({ name: r.name, nominal: r.nominal ?? null, unit: r.unit ?? "mm", min: r.min, max: r.max, origin: "set" })),
    ...add.map((n) => {
      const p = pool.find((x) => x.name === n);
      return { name: n, nominal: p?.nominal ?? null, unit: p?.unit ?? "mm", min: p?.default_range.min ?? 0, max: p?.default_range.max ?? 0, origin: "added" };
    }),
  ];
  const rows: VarRow[] = eff.map((e) => {
    const p = pool.find((x) => x.name === e.name);
    return { name: e.name, origin: e.origin, nominal: e.nominal, base: { min: e.min, max: e.max }, train: p?.train ?? null, feasible: p?.feasible ?? null, unit: e.unit, position: p?.position ?? false };
  });
  const params = eff.map((e) => ({ ...(ps.parameters.find((p) => p.name === e.name) ?? { unit: e.unit }), name: e.name, nominal: e.nominal ?? 0, min: e.min, max: e.max }));
  return { error, out: { ps: ps.engine === "native" ? { ...ps, parameters: params } : ps, rows, excluded: exclude, edited: add.length + exclude.length > 0 } };
}

/** 경고(학습·모핑 가능 범위 밖·양면 접촉·공칭 밖). bounds = 이름 → [lo, hi](없으면 기준 범위). 학습 범위를 모르면 안내 1줄 */
export function runNotes(srv: MockServer, rv: RunVars, bounds: Record<string, number[]> | null | undefined, modelId: string | null | undefined): VarNote[] {
  const notes: VarNote[] = [];
  for (const r of rv.rows) {
    const [lo, hi] = bounds?.[r.name] ?? [r.base.min, r.base.max];
    const tag = `'${r.name}' `;
    if (exceedsTrain(lo, hi, r.train)) notes.push({ code: "VAR_OUT_OF_TRAIN", name: r.name, message: `${tag}${NOTE_TEXT.VAR_OUT_OF_TRAIN}(학습 ${r.train!.min}~${r.train!.max})` });
    if (exceedsFeasibleRange(lo, hi, r.feasible)) notes.push({ code: "VAR_OUT_OF_FEASIBLE", name: r.name, message: `${tag}${NOTE_TEXT.VAR_OUT_OF_FEASIBLE}(모핑 가능 ${r.feasible?.min ?? "–"}~${r.feasible?.max ?? "–"})` });
    if (poolOf(srv, rv.ps, null).find((p) => p.name === r.name)?.ref_locked) notes.push({ code: "VAR_REF_LOCKED", name: r.name, message: `${tag}${NOTE_TEXT.VAR_REF_LOCKED}` });
    if (r.nominal != null && (r.nominal < lo || r.nominal > hi)) notes.push({ code: "VAR_NOMINAL_OUTSIDE", name: r.name, message: `${tag}${NOTE_TEXT.VAR_NOMINAL_OUTSIDE}` });
  }
  if (rv.ps.engine === "native" && !hasModel(srv, modelId)) notes.push({ code: "TRAIN_RANGE_UNKNOWN", message: NOTE_TEXT.TRAIN_RANGE_UNKNOWN });
  return notes;
}

/** 배치·최적화 기록에 남기는 스냅숏(§4.1) */
export function snapshotOf(ps: ParamSet, rv: RunVars) {
  return {
    schema_version: 1, set_revision: ps.native?.vars_revision ?? 0, edited: rv.edited,
    variables: rv.rows.map((r) => ({ name: r.name, nominal: r.nominal, min: r.base.min, max: r.base.max, unit: r.unit, origin: r.origin, train: r.train, feasible: r.feasible })),
    excluded: rv.excluded, train_source: null,
  };
}
