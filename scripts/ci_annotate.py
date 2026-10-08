"""CI 실패 로그를 GitHub 주석(::error)으로 남긴다 — 로그 원문을 내려받을 수 없는 환경에서도 API로 원인을 볼 수 있게.

사용: python scripts/ci_annotate.py <로그 파일> <제목> [줄 수=200]
로그 끝 N줄을 최대 4개 주석으로 나눠 출력한다(주석 한도: 단계당 error 10개).
"""

from __future__ import annotations

import sys
from pathlib import Path


def esc(s: str) -> str:
    return s.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main() -> int:
    path, title = Path(sys.argv[1]), sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 200
    if not path.is_file():
        print(f"::error title={esc(title)}::로그 파일 없음: {path}")
        return 0
    raw = path.read_bytes()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", errors="replace")
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()][-n:]
    size = max(1, -(-len(lines) // 4))
    chunks = [lines[i:i + size] for i in range(0, len(lines), size)][:4]
    for i, ch in enumerate(chunks, 1):
        body = "\n".join(x[:400] for x in ch)
        print(f"::error title={esc(f'{title} ({i}/{len(chunks)})')}::{esc(body)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
