"""비밀 마스킹(§11.3, phase2 §10.2).

- Masker: step 로그용. logging.mask_patterns만 적용(1차 §11.3).
- BundleMasker: 오류 묶음·운영 파일 로그용. mask_patterns + 고정 규칙(DB URL 자격 증명, Bearer, 쿠키, 비밀 환경변수 값).
두 마스커의 규칙은 일부러 합치지 않는다(step 로그에 규칙을 더하면 동작 변경).
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
from collections.abc import Mapping
from typing import Any


class Masker:
    def __init__(self, patterns: list[str]) -> None:
        self._rx = [re.compile(p) for p in patterns]

    def __call__(self, line: str) -> str:
        for rx in self._rx:
            line = rx.sub(lambda m: (m.group(1) + "=***") if m.groups() else "***", line)
        return line


SECRET_ENV_PATTERNS = ("*PASSWORD*", "*SECRET*", "*TOKEN*", "PG*")


class BundleMasker:
    def __init__(self, mask_patterns: list[str], cookie_name: str, url_env: str,
                 environ: Mapping[str, str] | None = None) -> None:
        self._user = [re.compile(p) for p in mask_patterns]
        self._fixed: list[tuple[re.Pattern[str], str]] = [
            (re.compile(r"(postgres(?:ql)?(?:\+\w+)?://)[^@\s]+@"), r"\1***@"),  # 계약 §10.2 규칙 그대로
            (re.compile(r"(?i)\bBearer\s+\S+"), "Bearer ***"),
            (re.compile(re.escape(cookie_name) + r"=[^\s;,\"']+"), f"{cookie_name}=***"),
        ]
        env = dict(os.environ if environ is None else environ)
        names = {url_env.upper()}
        secrets: list[str] = []
        for k, v in env.items():
            if k.upper() in names or any(fnmatch.fnmatchcase(k.upper(), p) for p in SECRET_ENV_PATTERNS):
                if v and len(v) >= 4:
                    secrets.append(v)
                    # JSON 항목(job.json 등)에 이스케이프된 형태로 들어간 값도 치환
                    secrets.append(json.dumps(v)[1:-1])
                    secrets.append(json.dumps(v, ensure_ascii=False)[1:-1])
                self._fixed.append((re.compile(r"\b" + re.escape(k) + r"=\S+"), f"{k}=***"))
        self._secrets = sorted(set(secrets), key=len, reverse=True)

    def __call__(self, text: str) -> str:
        for s in self._secrets:
            text = text.replace(s, "***")
        for rx, rep in self._fixed:
            text = rx.sub(rep, text)
        for rx in self._user:
            text = rx.sub(lambda m: (m.group(1) + "=***") if m.groups() else "***", text)
        return text


def bundle_masker(settings: Any) -> BundleMasker:
    """설정에서 BundleMasker 생성(오류 묶음·운영 로그·워커 환경 점검이 같은 규칙을 쓴다)."""
    return BundleMasker(settings.logging.mask_patterns, settings.auth.cookie_name, settings.database.url_env)
