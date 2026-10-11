"""PhysicsAI 시연 모드 준비(fake tools 배포판). start-demo.ps1이 부르며, 직접 실행해도 된다.

  python demo_setup.py init --root <시연 폴더> [--port 8100] [--frontend <프런트 빌드 폴더>]
      시연 폴더 아래에 ai_root·import·spdm·resources·tools·state·config 를 만들고
      config/platform.demo.yaml 템플릿을 채워 <시연 폴더>/config/platform.yaml 을 쓴다.
      가짜 도구: Windows는 실행 파일(.exe 런처, pip 내장 distlib), 그 밖은 실행 권한 스크립트.
  python demo_setup.py seed --root <시연 폴더> --url http://127.0.0.1:<port>
      (백엔드가 떠 있어야 함) 파워 사용자로 시연 Study 1개를 만들고 ①~⑤ 시연용 샘플 데이터를 넣는다.
      이미 있으면 그대로 둔다(덮어쓰기·삭제 없음).

  python demo_setup.py db-up --root <시연 폴더> --pg-bin <PostgreSQL bin 폴더> [--pg-port 55432]
      시연 전용 PostgreSQL 클러스터(<시연 폴더>/pgdata, 127.0.0.1만, trust 인증)를 만들고(없을 때만) 시작,
      DB physicsai_demo를 만든다. 기존 PostgreSQL을 쓰려면 이 단계 대신 PHYSICSAI_DATABASE_URL 환경변수를 준다.
  python demo_setup.py db-down --root <시연 폴더>      시연 클러스터 중지(파일은 그대로)
  python demo_setup.py up --root <시연 폴더>
      migration(upgrade head) → 백엔드 기동·health 확인 → seed → 워커 기동. 로그는 <시연 폴더>/logs,
      프로세스 정보는 <시연 폴더>/state/demo-procs.json. DB URL은 PHYSICSAI_DATABASE_URL(있으면) 또는 db-up 결과.
  python demo_setup.py down --root <시연 폴더>         백엔드·워커(와 자식 프로세스) 종료

경로 규칙: 시연 폴더 경로에 공백과 & | < > ^ % ! " ; , = ( ) 를 쓰지 않는다(플랫폼 경로 규칙).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE_DIR = os.path.dirname(os.path.abspath(__file__))
if HERE_DIR not in sys.path:  # 격리 실행(-I) 등으로 스크립트 폴더가 빠진 경우에도 같은 폴더 모듈을 찾는다
    sys.path.insert(0, HERE_DIR)
sys.dont_write_bytecode = True  # deploy/ 아래에 __pycache__를 만들지 않는다(정적 검사·오프라인 묶음 대상 폴더)

from demo_common import PKG_ROOT, _log  # noqa: E402
from demo_db import cmd_db_down, cmd_db_up  # noqa: E402
from demo_init import cmd_init  # noqa: E402
from demo_seed import cmd_seed  # noqa: E402


# ---------------------------------------------------------------------------
# 백엔드·워커 기동/종료(up / down)
# ---------------------------------------------------------------------------

PROCS_FILE = "demo-procs.json"


def _database_url(root: Path) -> str:
    url = os.environ.get("PHYSICSAI_DATABASE_URL")
    if url:
        return url
    f = root / "state" / "demo-db.json"
    if f.is_file():
        return json.loads(f.read_text(encoding="utf-8"))["url"]
    raise SystemExit("DB 접속 정보가 없습니다: db-up을 먼저 실행하거나 PHYSICSAI_DATABASE_URL 환경변수를 설정하세요")


def _child_env(root: Path, url: str) -> dict[str, str]:
    env = dict(os.environ)
    env.update({"PHYSICSAI_CONFIG": str(root / "config" / "platform.yaml"), "PHYSICSAI_DATABASE_URL": url,
                "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
    env.setdefault("FAKE_DEMO_DELAY_S", "3")
    if (PKG_ROOT / "backend" / "physicsai_api").is_dir():  # 저장소에서 실행(설치본은 venv에 패키지가 있음)
        env["PYTHONPATH"] = os.pathsep.join([str(PKG_ROOT / "backend"), str(PKG_ROOT / "worker"),
                                             str(PKG_ROOT / "packages" / "simdash_adapters" / "src")] +
                                            ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    return env


def _spawn(argv: list[str], env: dict[str, str], log: Path, cwd: Path) -> subprocess.Popen:
    kw: dict = {}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP(콘솔 창 닫혀도 유지)
    else:
        kw["start_new_session"] = True
    fh = open(log, "ab")  # noqa: SIM115 - 자식 프로세스가 계속 쓴다
    return subprocess.Popen(argv, env=env, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=fh, stderr=subprocess.STDOUT, **kw)


def _proc_alive(info: dict) -> bool:
    try:
        import psutil

        p = psutil.Process(info["pid"])
        return abs(p.create_time() - info["create_time"]) < 1.0 and p.status() != psutil.STATUS_ZOMBIE
    except Exception:  # noqa: BLE001
        return False


def _health(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/physicsai/api/health", timeout=2) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8")).get("status") == "ok"
    except Exception:  # noqa: BLE001
        return False


def cmd_up(args: argparse.Namespace) -> int:
    import psutil

    root = Path(args.root).resolve()
    cfg = root / "config" / "platform.yaml"
    if not cfg.is_file():
        raise SystemExit(f"시연 설정이 없습니다: {cfg} — init을 먼저 실행하세요")
    sys.path[:0] = [str(PKG_ROOT / "backend"), str(PKG_ROOT / "worker")]
    from physicsai_core.config import load_config

    lc = load_config(str(cfg), environ={})
    if not lc.ok:
        raise SystemExit("시연 설정 검증 실패: " + "; ".join(f"{i.key}: {i.message}" for i in lc.issues))
    port = lc.settings.server.port
    state = root / "state" / PROCS_FILE
    if state.is_file():
        old = json.loads(state.read_text(encoding="utf-8"))
        if any(_proc_alive(v) for v in old.values()):
            _log(f"이미 실행 중입니다: http://127.0.0.1:{port}/  (끝내려면 down)")
            print(json.dumps({"url": f"http://127.0.0.1:{port}/", "already_running": True}))
            return 0
    if _health(port):
        raise SystemExit(f"포트 {port}를 다른 프로그램이 쓰고 있습니다 — init --port로 바꾸세요")
    url = _database_url(root)
    env = _child_env(root, url)
    logs = root / "logs"
    logs.mkdir(exist_ok=True)
    r = subprocess.run([sys.executable, "-m", "alembic", "-c", str(PKG_ROOT / "migrations" / "alembic.ini"), "upgrade", "head"],
                       env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise SystemExit(f"DB migration 실패: {r.stderr[-2000:]}")
    procs: dict[str, dict] = {}
    be = _spawn([sys.executable, "-m", "physicsai_api.serve"], env, logs / "backend.out.log", root)
    procs["backend"] = {"pid": be.pid, "create_time": psutil.Process(be.pid).create_time()}
    state.write_text(json.dumps(procs), encoding="utf-8")
    end = time.time() + float(args.timeout)
    while not _health(port):
        if be.poll() is not None or time.time() > end:
            raise SystemExit(f"백엔드 기동 실패 — {logs / 'backend.out.log'}·{logs / 'backend.log'} 확인")
        time.sleep(0.5)
    _log(f"백엔드 기동: http://127.0.0.1:{port}/")
    seed = argparse.Namespace(root=str(root), url=f"http://127.0.0.1:{port}")
    cmd_seed(seed)
    wk = _spawn([sys.executable, "-m", "physicsai_worker", "--config", str(cfg)], env, logs / "worker.out.log", root)
    procs["worker"] = {"pid": wk.pid, "create_time": psutil.Process(wk.pid).create_time()}
    state.write_text(json.dumps(procs), encoding="utf-8")
    time.sleep(1.0)
    if wk.poll() is not None:
        raise SystemExit(f"워커 기동 실패 — {logs / 'worker.out.log'}·{logs / 'worker.log'} 확인")
    _log(f"워커 기동(가짜 도구 지연 {env['FAKE_DEMO_DELAY_S']}초)")
    _log(f"브라우저에서 http://127.0.0.1:{port}/ 을 열고 시연 사용자(관리자·파워·일반)를 고르세요")
    print(json.dumps({"url": f"http://127.0.0.1:{port}/", "already_running": False}))
    return 0


def cmd_down(args: argparse.Namespace) -> int:
    import psutil

    root = Path(args.root).resolve()
    state = root / "state" / PROCS_FILE
    if not state.is_file():
        _log("실행 정보가 없습니다")
        return 0
    procs = json.loads(state.read_text(encoding="utf-8"))
    for name in ("worker", "backend"):  # 워커 먼저(자식 도구 포함 트리)
        info = procs.get(name)
        if not info or not _proc_alive(info):
            continue
        p = psutil.Process(info["pid"])
        tree = [*p.children(recursive=True), p]
        for q in tree:
            try:
                q.terminate()
            except psutil.NoSuchProcess:
                pass
        _gone, alive = psutil.wait_procs(tree, timeout=15)
        for q in alive:
            try:
                q.kill()
            except psutil.NoSuchProcess:
                pass
        _log(f"{'워커' if name == 'worker' else '백엔드'} 종료")
    state.write_text("{}", encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    # 영문 Windows(cp1252) 파이프 출력에서도 한글 안내 때문에 죽지 않게(표현 못 하는 글자는 ?)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="demo_setup", description="PhysicsAI 시연 모드 준비")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("init", help="시연 폴더·가짜 도구·설정 만들기")
    a.add_argument("--root", required=True)
    a.add_argument("--port", type=int, default=8100)
    a.add_argument("--frontend", default="")
    a.set_defaults(func=cmd_init)
    b = sub.add_parser("seed", help="시연 Study·샘플 데이터 넣기(백엔드 기동 후)")
    b.add_argument("--root", required=True)
    b.add_argument("--url", required=True)
    b.set_defaults(func=cmd_seed)
    c = sub.add_parser("db-up", help="시연 전용 PostgreSQL 클러스터 준비·시작")
    c.add_argument("--root", required=True)
    c.add_argument("--pg-bin", required=True)
    c.add_argument("--pg-port", type=int, default=55432)
    c.set_defaults(func=cmd_db_up)
    d = sub.add_parser("db-down", help="시연 전용 PostgreSQL 중지")
    d.add_argument("--root", required=True)
    d.set_defaults(func=cmd_db_down)
    e = sub.add_parser("up", help="migration·백엔드·seed·워커 기동")
    e.add_argument("--root", required=True)
    e.add_argument("--timeout", type=float, default=90)
    e.set_defaults(func=cmd_up)
    f = sub.add_parser("down", help="백엔드·워커 종료")
    f.add_argument("--root", required=True)
    f.set_defaults(func=cmd_down)
    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
