"""조립 매칭 공용 검사(asm-match.md §6.3·§6.4): 입력 변경(STALE) 판정과 소비자(DOE·세트 등록)의 확정본 게이트.

STALE = 매칭 이후 입력이 바뀜: 조립 include 트리 digest · STEP sha256 · 피처 파일 sha256. 파일 내용 해시는 (경로·크기·mtime)로 캐시한다.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from physicsai_core.errors import DomainError
from physicsai_core.geometry import asm_match as am
from physicsai_core.geometry.asm_tree import digest_of
from physicsai_core.geometry.prep import sha256_file
from physicsai_core.paths import resolve_in_study

from ..context import AppContext
from .common import study_root

STALE_ASSEM = "조립 폴더의 파일이 매칭 이후 바뀌었습니다 — 조립 매칭을 다시 하세요"
STALE_CAD = "STEP 파일이 매칭 이후 바뀌었습니다 — 조립 매칭을 다시 하세요"
STALE_FEATURES = "형상 피처 파일이 매칭 이후 바뀌었습니다 — 조립 매칭을 다시 하세요"
NO_MATCH_MESSAGE = "조립 매칭을 먼저 하세요 — 조립 매칭 카드에서 STEP 바디와 조립 component를 매칭해 저장하세요(조립 매칭을 저장하세요)"


def valid_id(match_id: str) -> bool:
    try:
        return str(uuid.UUID(match_id)) == match_id.lower()
    except (ValueError, AttributeError):
        return False


def source_files(ctx: AppContext, study: dict[str, Any], source: dict[str, Any]) -> tuple[str | None, str | None]:
    """매칭 출처의 현재 STEP·피처 파일 절대 경로(없으면 None). train = Study 안(`cad_rel`·`features_rel`), path = 사용자 경로(`cad_path`)."""
    root = study_root(ctx, study)
    if source.get("kind") == am.KIND_TRAIN:
        cad = resolve_in_study(root, source["cad_rel"]) if source.get("cad_rel") else None
        feat = resolve_in_study(root, source["features_rel"]) if source.get("features_rel") else None
        return cad, feat
    return source.get("cad_path"), None


def _sha(path: str | None) -> str | None:
    try:
        return sha256_file(path) if path and os.path.isfile(path) else None
    except OSError:
        return None


def stale_reason(ctx: AppContext, study: dict[str, Any], match: dict[str, Any], digest: str | None) -> str | None:
    """입력 변경 사유(한국어) 또는 None. digest = 매칭 때(asm_parts.json)의 조립 트리 digest(모르면 조립 검사 생략)."""
    src = match.get("source") or {}
    cad, feat = source_files(ctx, study, src)
    if src.get("cad_sha256") and _sha(cad) != src["cad_sha256"]:
        return STALE_CAD
    if src.get("features_sha256") and _sha(feat) != src["features_sha256"]:
        return STALE_FEATURES
    if digest is not None and digest_of((match.get("assem") or {}).get("path") or "") != digest:
        return STALE_ASSEM
    return None


def confirmed_of(ctx: AppContext, study: dict[str, Any], match_id: str) -> tuple[dict[str, Any], str, str, dict[str, Any]] | None:
    """확정본 (문서, sha256, 경로, match.json) — 없으면 None."""
    if not valid_id(match_id):
        return None
    mdir = am.match_dir(study_root(ctx, study), match_id)
    path = os.path.join(mdir, am.CONFIRMED_JSON)
    doc, match = am.read_json(path), am.read_match(mdir)
    if doc is None or match is None or match.get("match_id") != match_id:
        return None
    return doc, sha256_file(path), path, match


def require_confirmed(ctx: AppContext, study: dict[str, Any], match_id: str, *, assem_path: str | None = None,
                      source_kind: str | None = None) -> dict[str, Any]:
    """소비자(DOE·세트 등록)용 게이트: 확정본이 있고 입력이 그대로여야 한다.
    없음·미확정 → 409 PREREQUISITE_MISSING(missing ASM_MATCH), 입력 변경·출처 불일치 → 409 ASM_MATCH_STALE.
    반환 {doc, sha256, path, match}. assem_path = 소비자가 쓸 조립 폴더(트리 digest가 확정본과 같아야 함, 생략 = 매칭의 경로)."""
    got = confirmed_of(ctx, study, match_id)
    if got is None:
        raise DomainError("PREREQUISITE_MISSING", NO_MATCH_MESSAGE, status=409, missing=["ASM_MATCH"])
    doc, sha, path, match = got
    src = match.get("source") or {}
    if source_kind is not None and src.get("kind") != source_kind:
        raise DomainError("ASM_MATCH_STALE", "이 조립 매칭의 STEP 출처가 이 작업과 다릅니다 — 조립 매칭을 다시 하세요", status=409,
                          match_id=match_id)
    why = stale_reason(ctx, study, match, None)
    if why is None:
        want = (doc.get("assem") or {}).get("digest")
        if digest_of(assem_path or (match.get("assem") or {}).get("path") or "") != want:
            why = STALE_ASSEM
    if why is not None:
        raise DomainError("ASM_MATCH_STALE", why, status=409, match_id=match_id)
    return {"doc": doc, "sha256": sha, "path": path, "match": match}


def require_for_set(ctx: AppContext, study: dict[str, Any], match_id: str, *, cad_path: str | None, assem_path: str | None) -> dict[str, Any]:
    """④ 세트 등록(asm-match.md §6.4 PARAM_SET_NATIVE)용 게이트: source=path 확정본 + 세트 STEP의 sha256 = 매칭의 STEP sha256 +
    조립 폴더 트리 digest = 확정본. 다르면 409 ASM_MATCH_STALE. 세트 STEP은 파일 1개여야 한다(parts 폴더는 422 ASM_MATCH_UNSUPPORTED)."""
    if not cad_path or os.path.isdir(cad_path):
        raise DomainError("ASM_MATCH_UNSUPPORTED", "조립 매칭은 STEP 파일 1개일 때만 쓸 수 있습니다(parts 폴더 불가)", status=422)
    got = require_confirmed(ctx, study, match_id, assem_path=assem_path, source_kind=am.KIND_PATH)
    want = ((got["match"].get("source") or {}).get("cad_sha256"))
    if _sha(cad_path) != want:
        raise DomainError("ASM_MATCH_STALE", "등록하려는 STEP이 조립 매칭의 STEP과 다릅니다 — 조립 매칭을 다시 하세요", status=409, match_id=match_id)
    return got
