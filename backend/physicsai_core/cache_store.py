"""서버측 플랫폼 임시 캐시 삭제의 유일한 지점(geometry-view.md GV-8·§6.6).

AGENTS.md "사용자 산출물 삭제 금지(_backup 이동)"의 계약상 예외: AI 루트 `<study>/_cache/{geom_preview,contour3d}/` 아래 미리보기·3D
컨투어 캐시는 입력에서 언제든 재생성되는 플랫폼 임시 산출물이라 `_backup` 이동 대신 삭제한다. 그 밖 경로는 여기서도 지우지 않는다 —
삭제 전 실경로가 `<study>/<prefix>/` 아래이고 경로 위에 링크·reparse point가 없는지 확인한다(아니면 False, 아무것도 지우지 않음).
정적 시험(삭제 호출 금지)의 허용 목록은 이 파일 하나뿐이다.
"""

from __future__ import annotations

import os
import shutil

from .geometry.view import safe_cache_dir


def remove_cache_dir(study_root: str, path: str, prefix: str) -> bool:
    """캐시 폴더 1개 삭제. 확인 실패(경로 탈출·링크)면 False(삭제 없음). 없으면 True."""
    if not os.path.lexists(path):
        return True
    if not safe_cache_dir(study_root, path, prefix) or not os.path.isdir(path):
        return False
    shutil.rmtree(path)
    return True


def remove_cache_file(study_root: str, path: str, prefix: str) -> bool:
    """캐시 폴더 안 임시 파일 1개 삭제(같은 확인)."""
    if not os.path.lexists(path):
        return True
    if not safe_cache_dir(study_root, path, prefix) or not os.path.isfile(path):
        return False
    os.remove(path)
    return True
