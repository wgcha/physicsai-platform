"""프런트 빌드 입력(소스)의 해시 — frontend-dist/BUILD_INFO.json의 source_hash (phase3 D3-40).

같은 규칙을 deploy/node-select.ps1 Get-PhysicsAIFrontendSourceHash가 PowerShell로 구현한다(Python 없이도 서버에서 판정,
동일성 시험: backend/tests/test_runtime_install.py).

규칙
  대상: frontend/ 아래 index.html, package.json, package-lock.json, vite.config.*, tsconfig*.json(최상위 파일)
        + src/**, public/**(모든 파일). node_modules·dist는 대상 밖.
  경로: frontend/ 기준 상대경로, 구분자 '/', 서수(코드 단위) 정렬.
  내용: 바이트의 CRLF를 LF로 바꾼 뒤 sha256(Windows autocrlf 체크아웃과 Linux 체크아웃이 같은 값).
  결과: sha256( Σ "<경로>\\0<내용 sha256 hex>\\n" (UTF-8) ) hex 소문자.

사용: python scripts/frontend_source_hash.py [frontend 폴더]          → 해시 출력
      python scripts/frontend_source_hash.py --check [저장소 루트]     → frontend-dist가 최신이면 0, 아니면 안내 후 1
      python scripts/frontend_source_hash.py --write-info <저장소 루트> <vite_version> <node_version>
                                                                     → frontend-dist/BUILD_INFO.json 작성(scripts/build-frontend-dist)
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

TOP_PATTERNS = ("index.html", "package.json", "package-lock.json", "vite.config.*", "tsconfig*.json")
TREES = ("src", "public")
STALE_MESSAGE = "frontend-dist가 최신이 아닙니다: scripts/build-frontend-dist 실행 후 커밋"


def source_files(frontend: Path) -> list[str]:
    out: list[str] = []
    if frontend.is_dir():
        for p in frontend.iterdir():
            if p.is_file() and any(fnmatch.fnmatchcase(p.name, pat) for pat in TOP_PATTERNS):
                out.append(p.name)
    for tree in TREES:
        root = frontend / tree
        if root.is_dir():
            out.extend(p.relative_to(frontend).as_posix() for p in root.rglob("*") if p.is_file())
    # 서수 정렬: PowerShell [StringComparer]::Ordinal(UTF-16 코드 단위)과 같게 — BMP 밖 문자도 일치하도록 UTF-16 기준
    return sorted(out, key=lambda s: s.encode("utf-16-be"))


def source_hash(frontend: Path) -> str:
    h = hashlib.sha256()
    for rel in source_files(frontend):
        data = (frontend / rel).read_bytes().replace(b"\r\n", b"\n")
        h.update(rel.encode("utf-8") + b"\0" + hashlib.sha256(data).hexdigest().encode("ascii") + b"\n")
    return h.hexdigest()


def check(repo: Path) -> tuple[bool, str]:
    info = repo / "frontend-dist" / "BUILD_INFO.json"
    if not info.is_file():
        return False, f"{STALE_MESSAGE} (frontend-dist/BUILD_INFO.json 없음)"
    try:
        recorded = json.loads(info.read_text(encoding="utf-8")).get("source_hash", "")
    except (OSError, ValueError) as exc:
        return False, f"{STALE_MESSAGE} (BUILD_INFO.json을 읽을 수 없음: {exc})"
    if not (repo / "frontend-dist" / "index.html").is_file():
        return False, f"{STALE_MESSAGE} (frontend-dist/index.html 없음)"
    current = source_hash(repo / "frontend")
    if recorded != current:
        return False, f"{STALE_MESSAGE} (기록 {recorded[:12] or '-'} ≠ 현재 소스 {current[:12]})"
    return True, f"frontend-dist 최신(source_hash {current[:12]})"


def write_info(repo: Path, vite_version: str, node_version: str) -> dict:
    info = {
        "source_hash": source_hash(repo / "frontend"),
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "vite_version": vite_version,
        "node_version": node_version,
    }
    (repo / "frontend-dist" / "BUILD_INFO.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8", newline="\n")
    return info


def main(argv: list[str]) -> int:
    if argv and argv[0] == "--write-info" and len(argv) == 4:
        print(json.dumps(write_info(Path(argv[1]), argv[2], argv[3])))
        return 0
    if argv and argv[0] == "--check":
        repo = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent
        ok, msg = check(repo)
        print(msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1
    frontend = Path(argv[0]) if argv else Path(__file__).resolve().parent.parent / "frontend"
    print(source_hash(frontend))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
