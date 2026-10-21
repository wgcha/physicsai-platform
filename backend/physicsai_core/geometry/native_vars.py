"""Native 템플릿 변수 정의(선택·범위) 공용 순수 함수(native-vars.md §3~§5) — 표준 라이브러리만, I/O·DB 없음.

- `pool`: 변수 풀 = 피처 파일의 그룹 대표 + 그룹 없는 피처(NV-1, `features_view.representative_params`와 같은 규칙, 쉘은 기본 대상
  component의 피처). 사용자 정의(사용 여부·하한·상한)는 풀 안에서만 정한다.
- `effective`: 유효 변수 = (세트 정의 − exclude) + add → 실행 스냅숏 `vars`(§4.1)와 요청 오류 목록.
- `apply`: 스냅숏을 세트 사본 `ps'`에 반영(`parameters`만 바뀜). 워커·API는 `apply` 결과를 기존 함수에 넘긴다(시그니처 불변).
- `warn_rows`·`warn_points`: 범위 경고(차단 없음, NV-7). 학습 범위·모핑 가능 범위 밖 = `VAR_OUT_OF_TRAIN`·`VAR_OUT_OF_FEASIBLE`.
- `train_ranges`: 학습 범위 합집합(NV-8, §5.2) 순수부 — DOE 조회·파일 읽기는 호출부(API 서비스)가 한다.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .extract_filter import GROUP_TYPES
from .features_view import feature_rows

SCHEMA_VERSION = 1
POSITION_TYPES = frozenset(GROUP_TYPES["position"])
DISPLAY_KEYS = ("origin", "train", "feasible", "ref_locked")  # 스냅숏 행 중 표시·경고 재현용 키(`apply`가 뺀다, ref_locked는 true일 때만 기록)
PROP_SOURCE = "prop"
SHELL_SOURCE = "shell"

TRAIN_TOL = 1e-9  # 학습 범위 비교 허용오차(× max(1, |x|)), 프런트 exceedsFeasible과 같은 규칙
FEASIBLE_TOL = 1e-9
SAME_FEATURE_TOL = 1e-6  # 학습 DOE 피처와 같은 피처인지(공칭 비교, × max(1, |nominal|))

NOTE_UNKNOWN = "TRAIN_RANGE_UNKNOWN"
NOTE_UNMATCHED = "TRAIN_RANGE_UNMATCHED"
UNKNOWN_MESSAGE = "모델의 학습 범위를 알 수 없어 외삽 경고를 생략합니다(모델의 데이터셋이 ① DOE 결과가 아님)"
MULTI_UNKNOWN_MESSAGE = "다중 baseline 템플릿은 학습 범위를 비교하지 않아 외삽 경고를 생략합니다"


def finite_num(v: Any) -> float | None:
    """유한한 수(bool 제외)면 float, 아니면 None."""
    return _num(v)


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def _g(x: float) -> str:
    return f"{x:g}"


# ---- 풀 -----------------------------------------------------------------------------------------------


def _rep_names(doc: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    members: set[str] = set()
    reps: set[str] = set()
    for g in doc.get("groups") or []:
        if isinstance(g, Mapping) and isinstance(g.get("parameter"), str):
            reps.add(g["parameter"])
            members |= {m for m in g.get("members", []) if isinstance(m, str)}
    return reps, members


def pool(doc: Mapping[str, Any] | None, *, kind: str = "solid", component: str | None = None) -> list[dict[str, Any]]:
    """변수 풀(피처 파일 순). 항목: name·type·body·nominal·unit·position·default_range{min,max}·feasible|None·ref_locked·group
    (+쉘 피처는 source="shell"). 범위·공칭이 없는 피처는 풀에서 뺀다(추가할 기본 범위가 없음)."""
    if not isinstance(doc, Mapping):
        return []
    shell_names: set[str] | None = None
    if kind == "shell":
        from .shell_native import shell_rows

        shell_names = {r["name"] for r in shell_rows(doc, component or "")[0]}
    reps, members = _rep_names(doc)
    out: list[dict[str, Any]] = []
    for r in feature_rows(dict(doc)):
        n = r["name"]
        if shell_names is not None:
            if n not in shell_names:
                continue
        elif not (n in reps or n not in members):
            continue
        if r["nominal"] is None or r["min"] is None or r["max"] is None:
            continue
        e: dict[str, Any] = {
            "name": n, "type": r["type"], "body": r["body"], "nominal": r["nominal"], "unit": r["unit"] or "mm",
            "position": r["type"] in POSITION_TYPES, "default_range": {"min": r["min"], "max": r["max"]},
            "feasible": r["feasible"], "ref_locked": bool(r["ref_locked"]), "group": r["group"]}
        if shell_names is not None:
            e["source"] = SHELL_SOURCE
        out.append(e)
    return out


def pool_names(entries: Iterable[Mapping[str, Any]]) -> list[str]:
    return [str(e["name"]) for e in entries]


def is_prop_row(row: Mapping[str, Any]) -> bool:
    return row.get("source") == PROP_SOURCE


# ---- 유효 변수(스냅숏) -----------------------------------------------------------------------------------


def _rng(v: Mapping[str, Any] | None) -> dict[str, float] | None:
    if not isinstance(v, Mapping):
        return None
    lo, hi = _num(v.get("min")), _num(v.get("max"))
    return {"min": lo, "max": hi} if lo is not None and hi is not None else None  # type: ignore[dict-item]


def _feas(v: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(v, Mapping):
        return None
    lo, hi = _num(v.get("min")), _num(v.get("max"))
    if lo is None and hi is None:
        return None
    return {"min": lo, "max": hi, "source": v.get("source")}


def _problem(field: str, name: str, message: str) -> dict[str, str]:
    return {"field": field, "name": name, "message": message}


def effective(set_rows: Sequence[Mapping[str, Any]], entries: Sequence[Mapping[str, Any]], *, add: Sequence[str] = (),
              exclude: Sequence[str] = (), train: Mapping[str, Mapping[str, float] | None] | None = None,
              set_revision: int = 0, train_source: Mapping[str, Any] | None = None
              ) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """(스냅숏 `vars`, 요청 오류 [{field, name, message}]). 오류가 있으면 스냅숏은 오류 항목을 무시한 값이다.

    유효 변수 = (세트 정의 − exclude) + add. 세트 행은 그대로(PROP·baselines 키 보존), 추가 변수는 피처 기본 범위, 순서 = 세트 순서 뒤에 풀 순서."""
    by_pool = {str(e["name"]): e for e in entries}
    set_names = [str(r["name"]) for r in set_rows]
    problems: list[dict[str, str]] = []
    seen: set[str] = set()
    for n in exclude:
        if n in seen:
            problems.append(_problem("vars.exclude", n, f"'{n}'이 제외 목록에 중복되었습니다"))
        elif n not in set_names:
            problems.append(_problem("vars.exclude", n, f"'{n}'은 세트 정의에 없는 변수라 제외할 수 없습니다"))
        seen.add(n)
    seen_a: set[str] = set()
    for n in add:
        if n in seen_a:
            problems.append(_problem("vars.add", n, f"'{n}'이 추가 목록에 중복되었습니다"))
        elif n in set_names:
            problems.append(_problem("vars.add", n, f"'{n}'은 이미 세트 정의에 있는 변수입니다"))
        elif n not in by_pool:
            problems.append(_problem("vars.add", n, f"'{n}'은 이 템플릿의 변수 풀에 없습니다 — 추출 조건을 바꿔 새 템플릿으로 등록하세요"))
        elif n in seen:
            problems.append(_problem("vars.add", n, f"'{n}'을 추가와 제외에 함께 쓸 수 없습니다"))
        seen_a.add(n)
    drop, plus = set(exclude), set(add)
    tr = train or {}
    rows: list[dict[str, Any]] = []
    for r in set_rows:
        n = str(r["name"])
        if n in drop:
            continue
        e = by_pool.get(n)
        rows.append({**r, "origin": "set", "train": _rng(tr.get(n)), "feasible": _feas(e.get("feasible")) if e else None,
                     **({"ref_locked": True} if e and e.get("ref_locked") else {})})
    for e in entries:  # 풀 순서
        n = str(e["name"])
        if n in plus and n not in set_names and n in by_pool:
            d = e["default_range"]
            row: dict[str, Any] = {"name": n, "nominal": e["nominal"], "min": d["min"], "max": d["max"], "unit": e.get("unit") or "mm"}
            if e.get("source"):
                row["source"] = e["source"]
            rows.append({**row, "origin": "added", "train": _rng(tr.get(n)), "feasible": _feas(e.get("feasible")),
                         **({"ref_locked": True} if e.get("ref_locked") else {})})
    doc = {"schema_version": SCHEMA_VERSION, "set_revision": int(set_revision), "edited": bool(add or exclude), "variables": rows,
           "excluded": [n for n in set_names if n in drop], "train_source": dict(train_source) if train_source else None}
    return doc, problems


def vars_of(container: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """기록 위치(`source_meta`·`settings`·job params)의 스냅숏 `vars`. 모양이 틀리면 None(= 이전 기록, 기존 경로)."""
    v = (container or {}).get("vars")
    if isinstance(v, Mapping) and isinstance(v.get("variables"), list) and v["variables"]:
        return dict(v)
    return None


def apply(ps: Mapping[str, Any], vars_doc: Mapping[str, Any] | None) -> dict[str, Any]:
    """`ps` 사본에서 `parameters`만 스냅숏 변수 행으로 바꾼다(표시용 키는 뺌). 스냅숏이 없으면 `ps` 그대로(사본)."""
    v = vars_of({"vars": vars_doc}) if vars_doc is not None else None
    if v is None:
        return dict(ps)
    rows = [{k: x for k, x in r.items() if k not in DISPLAY_KEYS} for r in v["variables"] if isinstance(r, Mapping)]
    return {**ps, "parameters": rows}


def variable_names(vars_doc: Mapping[str, Any]) -> list[str]:
    return [str(r["name"]) for r in vars_doc.get("variables") or []]


# ---- 경고 ---------------------------------------------------------------------------------------------


def _out(lo: float, hi: float, a: float | None, b: float | None, tol: float) -> bool:
    if a is not None and lo < a - tol * max(1.0, abs(a)):
        return True
    return b is not None and hi > b + tol * max(1.0, abs(b))


def _note(code: str, name: str, message: str) -> dict[str, str]:
    return {"code": code, "name": name, "message": message}


def _notes_for(v: Mapping[str, Any], lo: float, hi: float, ref_locked: bool) -> list[dict[str, str]]:
    n = str(v["name"])
    out: list[dict[str, str]] = []
    t = _rng(v.get("train"))
    if t is not None and _out(lo, hi, t["min"], t["max"], TRAIN_TOL):
        out.append(_note("VAR_OUT_OF_TRAIN", n, f"'{n}' 학습 형상 분포 밖 — 외삽 주의(학습 {_g(t['min'])}~{_g(t['max'])})"))
    f = _feas(v.get("feasible"))
    if f is not None and _out(lo, hi, f["min"], f["max"], FEASIBLE_TOL):
        out.append(_note("VAR_OUT_OF_FEASIBLE", n, "'{}' 모핑 실패 가능(모핑 가능 {}~{})".format(
            n, _g(f["min"]) if f["min"] is not None else "−∞", _g(f["max"]) if f["max"] is not None else "+∞")))
    if ref_locked:
        out.append(_note("VAR_REF_LOCKED", n, f"'{n}' 양면 접촉 피처 — 형상 생성이 실패할 수 있습니다"))
    nom = _num(v.get("nominal"))
    if nom is not None and (nom < lo - TRAIN_TOL * max(1.0, abs(lo)) or nom > hi + TRAIN_TOL * max(1.0, abs(hi))):
        out.append(_note("VAR_NOMINAL_OUTSIDE", n, f"'{n}' 공칭 {_g(nom)}이 범위 {_g(lo)}~{_g(hi)} 밖입니다(기준안은 범위 밖 점으로 표시)"))
    return out


def warn_rows(vars_doc: Mapping[str, Any], bounds: Mapping[str, Sequence[float]] | None = None) -> list[dict[str, str]]:
    """실행(또는 세트 정의) 범위의 경고 `{code, name, message}`. bounds[이름] 없으면 변수 기준 범위(min·max)."""
    out: list[dict[str, str]] = []
    for v in vars_doc.get("variables") or []:
        n = str(v["name"])
        b = (bounds or {}).get(n)
        lo = _num(b[0]) if b is not None and len(b) == 2 else None
        hi = _num(b[1]) if b is not None and len(b) == 2 else None
        if lo is None or hi is None:
            lo, hi = _num(v.get("min")), _num(v.get("max"))
        if lo is None or hi is None:
            continue
        out += _notes_for(v, lo, hi, bool(v.get("ref_locked")))
    return out


def warn_points(vars_doc: Mapping[str, Any], points: Sequence[Mapping[str, float]],
                bounds: Mapping[str, Sequence[float]] | None = None) -> list[dict[str, str]]:
    """⑥ 추가 검증 점 경고: 최적화 범위 밖(`VAR_OUT_OF_BOUNDS`)·학습 범위 밖·모핑 가능 범위 밖. 변수·코드마다 1건(첫 점)."""
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(w: dict[str, str]) -> None:
        k = (w["code"], w["name"])
        if k not in seen:
            seen.add(k)
            out.append(w)

    for i, pt in enumerate(points, 1):
        for v in vars_doc.get("variables") or []:
            n = str(v["name"])
            x = _num(pt.get(n))
            if x is None:
                continue
            b = (bounds or {}).get(n)
            if b is not None and len(b) == 2 and _out(x, x, _num(b[0]), _num(b[1]), TRAIN_TOL):
                add(_note("VAR_OUT_OF_BOUNDS", n, f"'{n}' 최적화 범위 밖 점입니다(점 {i}: {_g(x)}, 범위 {_g(float(b[0]))}~{_g(float(b[1]))})"))
            for w in _notes_for(v, x, x, False):
                if w["code"] in ("VAR_OUT_OF_TRAIN", "VAR_OUT_OF_FEASIBLE"):
                    add(w)
    return out


def var_rows(vars_doc: Mapping[str, Any], entries: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """미리보기 표 초기화 `var_rows`: name·origin·nominal·base{min,max}·train·feasible·unit·position."""
    typ = {str(e["name"]): e for e in entries}
    out = []
    for v in vars_doc.get("variables") or []:
        n = str(v["name"])
        out.append({"name": n, "origin": v.get("origin") or "set", "nominal": _num(v.get("nominal")),
                    "base": {"min": _num(v.get("min")), "max": _num(v.get("max"))}, "train": _rng(v.get("train")),
                    "feasible": _feas(v.get("feasible")), "unit": v.get("unit") or "",
                    "position": bool((typ.get(n) or {}).get("position"))})
    return out


def out_of_range_parameters(vars_doc: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    """Native 일괄 행 `out_of_range`(§5.3) 기준 = 학습 범위. 학습 범위를 아는 변수만 `{name, min, max}`(모르면 빈 목록)."""
    out = []
    for v in (vars_doc or {}).get("variables") or []:
        t = _rng(v.get("train"))
        if t is not None:
            out.append({"name": str(v["name"]), "min": t["min"], "max": t["max"]})
    return out


# ---- 학습 범위(순수부) -----------------------------------------------------------------------------------


def rep_features(doc: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """DOE 피처 파일의 대표 피처(그룹 대표 + 그룹 없는 피처) {이름: feature_rows 행}. component 필터 없음."""
    if not isinstance(doc, Mapping):
        return {}
    reps, members = _rep_names(doc)
    return {r["name"]: r for r in feature_rows(dict(doc)) if r["name"] in reps or r["name"] not in members}


def _same_feature(ident: Mapping[str, Any], f: Mapping[str, Any]) -> bool:
    if ident.get("type") != f.get("type") or (ident.get("body") or "") != (f.get("body") or ""):
        return False
    a, b = _num(ident.get("nominal")), _num(f.get("nominal"))
    return a is not None and b is not None and abs(a - b) <= SAME_FEATURE_TOL * max(1.0, abs(a))


def train_ranges(identities: Sequence[Mapping[str, Any]], does: Sequence[Mapping[str, Any]]
                 ) -> tuple[dict[str, dict[str, float] | None], list[dict[str, str]]]:
    """이름 → 학습 범위 합집합(모르면 None) + 안내 notes(TRAIN_RANGE_UNMATCHED).

    identities: [{name, type, body, nominal}] — 세트 풀 항목(쉘 두께 PROP 행은 type·body 없이 `prop: true`, 학습 snapshot 행과 이름·공칭으로만 대조).
    does: [{id, snapshot: [{name, nominal, min, max, unit}], features: 그 DOE 피처 파일 doc}] — READY·native DOE만 넘긴다.
    규칙(§5.2): DOE별 구간 = snapshot `[min, max]`, snapshot에 없고 DOE 대표 피처에 있으면 `[공칭, 공칭]`, 둘 다 없으면 그 이름은 None.
    같은 피처 확인(type·body·공칭)이 틀리면 None + UNMATCHED. snapshot의 `__na`·`baseline__*` 등 풀 밖 이름은 보지 않는다."""
    out: dict[str, dict[str, float] | None] = {}
    unmatched: list[str] = []
    feats = [rep_features(d.get("features")) for d in does]
    snaps = [{str(r.get("name")): r for r in d.get("snapshot") or [] if isinstance(r, Mapping)} for d in does]
    for ident in identities:
        n = str(ident["name"])
        lo: float | None = None
        hi: float | None = None
        ok = bool(does)
        for f, s in zip(feats, snaps):
            row = s.get(n)
            span: tuple[float, float] | None = None
            if ident.get("prop"):
                a, b = _num((ident or {}).get("nominal")), _num((row or {}).get("nominal"))
                if row is None or a is None or b is None or abs(a - b) > SAME_FEATURE_TOL * max(1.0, abs(a)):
                    ok = False
                    break
            else:
                fd = f.get(n)
                if fd is None:
                    ok = False
                    break
                if not _same_feature(ident, fd):
                    ok = False
                    unmatched.append(n)
                    break
            if row is not None and _num(row.get("min")) is not None and _num(row.get("max")) is not None:
                span = (float(row["min"]), float(row["max"]))
            elif not ident.get("prop") and _num(f[n].get("nominal")) is not None:
                span = (float(f[n]["nominal"]), float(f[n]["nominal"]))
            if span is None:
                ok = False
                break
            lo = span[0] if lo is None else min(lo, span[0])
            hi = span[1] if hi is None else max(hi, span[1])
        out[n] = {"min": lo, "max": hi} if ok and lo is not None and hi is not None else None
    notes = []
    if unmatched:
        shown = ", ".join(dict.fromkeys(unmatched))
        notes.append({"code": NOTE_UNMATCHED, "message": f"학습 데이터와 같은 피처인지 확인되지 않아 외삽 경고를 생략합니다(추출 조건이 다름): {shown}"})
    return out, notes
