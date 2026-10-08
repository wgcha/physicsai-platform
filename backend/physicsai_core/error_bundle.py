"""오류 묶음 항목 생성·마스킹(phase2 §10). zip 스트리밍은 API(B16 헬퍼)가 한다.

- 모든 텍스트 항목에 마스킹을 적용한다: logging.mask_patterns + 고정 규칙(DB URL 자격 증명, Bearer, 쿠키,
  비밀 환경변수 값).
- 로그는 꼬리만(UTF-8 경계 보정). Study 산출물 파일(h3d·psdata 등)은 넣지 않는다.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
from collections.abc import Iterator, Mapping
from typing import Any

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


def read_tail(path: str, limit: int) -> tuple[str, int]:
    """파일 꼬리 ≤ limit 바이트(UTF-8 경계 보정). (텍스트, 생략 바이트 수)."""
    size = os.path.getsize(path)
    start = max(0, size - limit)
    with open(path, "rb") as fh:
        fh.seek(start)
        data = fh.read(limit)
    skip = 0
    if start > 0:
        while skip < len(data) and skip < 4 and (data[skip] & 0xC0) == 0x80:
            skip += 1
    data = data[skip:]
    return data.decode("utf-8", errors="replace"), start + skip


def tail_item(path: str, limit: int) -> str:
    text, omitted = read_tail(path, limit)
    head = f"[앞 {omitted} 바이트 생략]\n" if omitted else ""
    return head + text


def json_bytes(data: Any) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8")


README = """PhysicsAI 오류 묶음
생성 시각(UTC): {created}
작업: {job_id} ({job_type}) 상태 {state} 실패 코드 {failure_code}

파일 설명
- job.json: 작업 정보(params·result·warnings·steps·failure·env_snapshot·retry_of)
- steps/step_NN_<key>.command.json: step 실행 명령(argv·cwd·추가 환경변수). 여러 대상 실행이면 commands.jsonl 앞 200줄 포함
- logs/*.log.tail.txt: 작업·step 로그 꼬리(파일당 최대 {tail} 바이트)
- hpc_jobs.json: PBS 제출 목록(있을 때)
- config_summary.json: 설정 요약(비밀·DB 접속 정보 제외)
- environment.json: 앱·Python·OS·migration·Altair 실행 파일·워커 정보
- env_check_latest.json: 최근 완료된 환경 점검 결과(없으면 null)
- TRUNCATED.txt: 크기 상한으로 넣지 못한 항목(있을 때)
비밀번호·토큰·DB 접속 정보·쿠키 값은 *** 로 가렸습니다.
"""


def iter_items(*, job: dict[str, Any], steps: list[dict[str, Any]], log_dir: str, study_root: str,
               hpc_jobs: list[dict[str, Any]] | None, config_summary: dict[str, Any], environment: dict[str, Any],
               env_check_latest: dict[str, Any] | None, tail_bytes: int, max_total: int, masker: BundleMasker,
               created: str) -> Iterator[tuple[str, bytes]]:
    """(zip 안 경로, 내용) 생성기. 압축 전 누적 ≥ max_total이면 남은 로그 항목은 TRUNCATED.txt 목록으로."""
    total = 0
    skipped: list[str] = []

    def emit(name: str, text: str) -> tuple[str, bytes]:
        nonlocal total
        b = masker(text).encode("utf-8")
        total += len(b)
        return name, b

    yield emit("README.txt", README.format(created=created, job_id=job["id"], job_type=job["job_type"], state=job["state"],
                                           failure_code=job.get("failure_code") or "-", tail=tail_bytes))
    yield emit("job.json", json_bytes(job).decode("utf-8"))
    for s in steps:
        name = f"steps/step_{s['step_no']:02d}_{s['step_key']}.command.json"
        cmd = dict(s.get("command") or {})
        rel = cmd.get("commands_rel")
        if rel:
            p = os.path.join(study_root, *str(rel).split("/"))
            if os.path.isfile(p) and os.path.realpath(p).startswith(os.path.realpath(study_root)):
                with open(p, encoding="utf-8", errors="replace") as fh:
                    lines = []
                    for i, line in enumerate(fh):
                        if i >= 200:
                            break
                        lines.append(line.rstrip("\n"))
                cmd["commands_head"] = lines
        yield emit(name, json_bytes({"step_no": s["step_no"], "step_key": s["step_key"], "command": cmd or None}).decode("utf-8"))
    if hpc_jobs:
        yield emit("hpc_jobs.json", json_bytes(hpc_jobs).decode("utf-8"))
    yield emit("config_summary.json", json_bytes(config_summary).decode("utf-8"))
    yield emit("environment.json", json_bytes(environment).decode("utf-8"))
    yield emit("env_check_latest.json", json_bytes(env_check_latest).decode("utf-8"))
    logs = [("logs/job.log.tail.txt", os.path.join(log_dir, "job.log"))]
    for s in steps:
        logs.append((f"logs/step_{s['step_no']:02d}_{s['step_key']}.log.tail.txt",
                     os.path.join(log_dir, f"step_{s['step_no']:02d}_{s['step_key']}.log")))
    for name, path in logs:
        if not os.path.isfile(path):
            continue
        if total >= max_total:
            skipped.append(name)
            continue
        yield emit(name, tail_item(path, min(tail_bytes, max(1024, max_total - total))))
    if skipped:
        yield emit("TRUNCATED.txt", "크기 상한(error_bundle.max_total_bytes)으로 넣지 못한 항목:\n" + "\n".join(skipped) + "\n")
