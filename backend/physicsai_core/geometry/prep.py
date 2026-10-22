"""native 준비본 `native/`(geometry-engine.md §4.2, §17.3): 경로·입력 sha256 기록·유효성(prep_status)."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any

from ..fileutil import sha256_file as _sha256_file
from .asm_match import ASM_MATCH_REL, is_matched
from .options import tag_options_sha256
from .reports import same_major_minor
from .shell import PROPS_JSON, SHELL_ONLY_KEY

_SHA_CACHE: dict[tuple[str, int, int], str] = {}
_SHA_CACHE_MAX = 512


def sha256_file(path: str) -> str:
    """sha256(경로·크기·수정시각이 같으면 캐시 — 목록 화면이 세트마다 큰 기준본을 매번 읽지 않게)."""
    st = os.stat(path)
    key = (os.path.abspath(path), st.st_size, st.st_mtime_ns)
    hit = _SHA_CACHE.get(key)
    if hit is None:
        hit = _sha256_file(path)
        if len(_SHA_CACHE) >= _SHA_CACHE_MAX:
            _SHA_CACHE.clear()
        _SHA_CACHE[key] = hit
    return hit


NATIVE_DIR = "native"
PREP_JSON = "native/prep.json"
FEATURES_JSON = "native/extract/parameter_features.json"
EXTRACTED_XML = "native/extract/parameter_extracted.xml"
FEATURES_DIR = "native/extract/features"
TAG_JSON = "native/tag/tag.json"
OPTIONS_JSON = "native/options.json"
READY, STALE, MISSING = "READY", "STALE", "MISSING"
STALE_MESSAGE_TAG = "경계 분류 기준이 바뀌어 형상 준비를 다시 해야 합니다"


@dataclass
class PrepState:
    status: str  # READY | STALE | MISSING
    reason: str | None = None  # 한국어(STALE·MISSING 사유)
    engine_version: str | None = None


def cad_inputs(S: str, step_exts: list[str]) -> dict[str, Any]:
    """S/cad의 입력 기록: 단일 STEP `{rel,sha256}` 또는 parts `{parts:[{rel,sha256}]}`(§4.2). body_map은 별도."""
    cad = os.path.join(S, "cad")
    exts = tuple(e.lower() for e in step_exts)
    single = sorted(n for n in os.listdir(cad) if os.path.isfile(os.path.join(cad, n)) and n.lower().endswith(exts)) if os.path.isdir(cad) else []
    if single:
        n = single[0]
        return {"rel": f"cad/{n}", "sha256": sha256_file(os.path.join(cad, n))}
    parts_dir = os.path.join(cad, "parts")
    parts = sorted(n for n in os.listdir(parts_dir) if n.lower().endswith(exts)) if os.path.isdir(parts_dir) else []
    return {"parts": [{"rel": f"cad/parts/{n}", "sha256": sha256_file(os.path.join(parts_dir, n))} for n in parts]}


def input_hashes(S: str, step_exts: list[str], mesh_include_name: str, renum_csv_name: str,
                 assem_dir: str | None = None) -> dict[str, Any]:
    """prep.json `inputs`(§4.2): step·baseline_inc·renum_csv·body_map. 파일이 없으면 해당 sha256은 None.
    assem_dir: 조립 폴더가 S/radioss_assem이 아닌 곳에 있을 때(①-3 DOE의 D 기준 준비본)."""
    assem = assem_dir or os.path.join(S, "radioss_assem")
    if is_matched(S):  # 조립 매칭 세트(asm-match.md §6.4): 기준본·RENUM 파일 대신 확정본 sha256 + include 트리 digest
        return matched_input_hashes(S, step_exts, assem)
    bm = os.path.join(S, "cad", "body_map.json")

    def one(name: str) -> dict[str, Any]:
        p = os.path.join(assem, name)
        return {"name": name, "sha256": sha256_file(p) if os.path.isfile(p) else None}

    return {"step": cad_inputs(S, step_exts), "baseline_inc": one(mesh_include_name), "renum_csv": one(renum_csv_name),
            "body_map": {"rel": "cad/body_map.json", "sha256": sha256_file(bm)} if os.path.isfile(bm) else None}


def matched_input_hashes(S: str, step_exts: list[str], assem_dir: str) -> dict[str, Any]:
    """조립 매칭 세트 prep.json `inputs`(asm-match.md §6.4): step + `asm_match{rel,sha256}` + `assem_digest`(include 트리).
    baseline_inc·renum_csv = null, body_map = null(BODY_MAP_IGNORED — 확정본이 유일한 대응)."""
    from .asm_tree import digest_of

    return {"step": cad_inputs(S, step_exts), "baseline_inc": None, "renum_csv": None, "body_map": None,
            "asm_match": {"rel": ASM_MATCH_REL, "sha256": sha256_file(os.path.join(S, *ASM_MATCH_REL.split("/")))},
            "assem_digest": digest_of(assem_dir)}


def shell_input_hashes(S: str, step_exts: list[str], assem_dir: str | None = None) -> dict[str, Any]:
    """쉘 세트 prep.json `inputs`(shell-morph.md §4.2): step·body_map + assem_digest, baseline_inc·renum_csv = null."""
    from .shell_native import assem_digest

    bm = os.path.join(S, "cad", "body_map.json")
    return {"step": cad_inputs(S, step_exts), "baseline_inc": None, "renum_csv": None,
            "body_map": {"rel": "cad/body_map.json", "sha256": sha256_file(bm)} if os.path.isfile(bm) else None,
            "assem_digest": assem_digest(assem_dir or os.path.join(S, "radioss_assem"))}


def prep_document(S: str, *, step_exts: list[str], mesh_include_name: str, renum_csv_name: str, opts: dict[str, Any],
                  engine_version: str | None, ocp_version: str | None, job_id: str | None, created_at: str,
                  assem_dir: str | None = None, shell_only: bool = False, kind: str = "solid",
                  component: str | None = None) -> dict[str, Any]:
    if kind == "shell":  # 쉘 판금(SM §4.2): opts = 유효 쉘 옵션, tag_options_sha256 = tag + fixed(전이 폭 제외) 절
        from .shell_native import fixed_digest
        from .shell_options import prep_options_sha256

        return {"schema_version": 1, "engine": "native", "engine_version": engine_version, "ocp_version": ocp_version,
                "kind": "shell", "inputs": shell_input_hashes(S, step_exts, assem_dir),
                "tag_options_sha256": prep_options_sha256(opts), "fixed_digest": fixed_digest(S), "component": component,
                "created_at": created_at, "job_id": job_id}
    doc = {"schema_version": 1, "engine": "native", "engine_version": engine_version, "ocp_version": ocp_version,
           "inputs": input_hashes(S, step_exts, mesh_include_name, renum_csv_name, assem_dir),
           "tag_options_sha256": tag_options_sha256(opts), "created_at": created_at, "job_id": job_id}
    if shell_only:  # 단계 3S 쉘 두께 전용 세트(§11.1): cad·extract·tag 없음, props.json만
        doc[SHELL_ONLY_KEY] = True
    return doc


def prep_kind(S: str) -> str:
    """prep.json `kind`(없으면 solid — 기존 준비본 호환, SM §4.2)."""
    prep = _read_prep(S)
    return "shell" if prep and prep.get("kind") == "shell" else "solid"


def is_shell_only(S: str) -> bool:
    """쉘 두께 전용 세트(prep.json `shell_only: true`) — tag·update·morph·check를 생략한다(§11.1)."""
    prep = _read_prep(S)
    return bool(prep and prep.get(SHELL_ONLY_KEY))


def _read_prep(S: str) -> dict[str, Any] | None:
    try:
        with open(os.path.join(S, PREP_JSON), encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def prep_state(S: str, *, step_exts: list[str], mesh_include_name: str, renum_csv_name: str, opts: dict[str, Any],
               current_engine_version: str | None = None, assem_dir: str | None = None) -> PrepState:
    """준비본 유효성(§4.2·§17.3): prep.json·features·tag.json 있음 + 입력 sha256 일치 + tag 옵션 sha256 일치 +
    engine_version MAJOR.MINOR 일치(현재 paicad 버전을 알 때만). 없음 → MISSING, 불일치 → STALE."""
    prep = _read_prep(S)
    if prep is not None and prep.get("kind") == "shell":
        return _shell_prep_state(S, prep, step_exts, opts, current_engine_version, assem_dir)
    need = (PROPS_JSON,) if (prep and prep.get(SHELL_ONLY_KEY)) else (FEATURES_JSON, TAG_JSON)
    if prep is None or any(not os.path.isfile(os.path.join(S, n)) for n in need):
        return PrepState(MISSING, "형상 준비 파일(native/)이 없습니다 — 형상 준비를 다시 실행하세요")
    ver = prep.get("engine_version") if isinstance(prep.get("engine_version"), str) else None
    now = input_hashes(S, step_exts, mesh_include_name, renum_csv_name, assem_dir)
    if prep.get("inputs") != now:
        what = "STEP·조립 매칭·조립 파일" if is_matched(S) else "STEP·기준 메시·번호 표"
        return PrepState(STALE, f"형상 준비 이후 입력({what})이 바뀌었습니다 — 형상 준비를 다시 하세요", ver)
    if not prep.get(SHELL_ONLY_KEY) and prep.get("tag_options_sha256") != tag_options_sha256(opts):
        return PrepState(STALE, STALE_MESSAGE_TAG, ver)
    if not same_major_minor(ver, current_engine_version):
        return PrepState(STALE, f"형상 엔진 버전이 바뀌었습니다({ver} → {current_engine_version}) — 형상 준비를 다시 하세요", ver)
    return PrepState(READY, None, ver)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _shell_prep_state(S: str, prep: dict[str, Any], step_exts: list[str], opts: dict[str, Any], current: str | None,
                      assem_dir: str | None) -> PrepState:
    """쉘 준비본 유효성(SM §4.2): 파일 존재 + inputs(step·body_map·assem_digest) 일치 + tag·fixed 절 sha256 일치 + 버전."""
    from .shell_native import SHELL_FEATURES_JSON, SHELL_SCAN_JSON, SHELL_TAG_JSON
    from .shell_options import prep_options_sha256

    if any(not os.path.isfile(os.path.join(S, *n.split("/"))) for n in (SHELL_FEATURES_JSON, SHELL_TAG_JSON, SHELL_SCAN_JSON)):
        return PrepState(MISSING, "쉘 형상 준비 파일(native/)이 없습니다 — 형상 준비를 다시 실행하세요")
    ver = prep.get("engine_version") if isinstance(prep.get("engine_version"), str) else None
    if prep.get("inputs") != shell_input_hashes(S, step_exts, assem_dir):
        return PrepState(STALE, "형상 준비 이후 입력(중립면 STEP·조립 폴더)이 바뀌었습니다 — 형상 준비를 다시 하세요", ver)
    if "fixed" in opts and prep.get("tag_options_sha256") != prep_options_sha256(opts):
        return PrepState(STALE, "경계 분류·고정 영역 기준이 바뀌어 형상 준비를 다시 해야 합니다", ver)
    if not same_major_minor(ver, current):
        return PrepState(STALE, f"형상 엔진 버전이 바뀌었습니다({ver} → {current}) — 형상 준비를 다시 하세요", ver)
    return PrepState(READY, None, ver)
