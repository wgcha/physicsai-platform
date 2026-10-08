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
import datetime as _dt
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG_ROOT = HERE.parents[1]  # 저장소 루트 또는 오프라인 묶음 루트
TOOLS = ("fake_edspy", "fake_simlab", "fake_hw", "fake_hstbatch", "fake_hstpy", "fake_hvtrans", "fake_nvidia_smi")
STUDY_FOLDER = "demo_bracket"
STUDY_TITLE = "시연 브래킷 낙하"
PROJECT_ID = "demo"
POWER_TOKEN = "demo-power"
UNSAFE = re.compile(r"[\s&|<>^%!\";,=()]")
# 모든 가짜 도구 맨 앞에 넣는 지연(FAKE_DEMO_DELAY_S초): 대기열·진행·취소를 눈으로 보게 한다
DELAY_PROLOGUE = 'import os as _o, time as _t; _t.sleep(float(_o.environ.get("FAKE_DEMO_DELAY_S") or 0))\n'


def _log(msg: str) -> None:
    print(f"[PhysicsAI 시연] {msg}", flush=True)


def fwd(p: Path | str) -> str:
    return str(p).replace("\\", "/")


def find_template() -> Path:
    for c in (PKG_ROOT / "config" / "platform.demo.yaml",):
        if c.is_file():
            return c
    raise SystemExit("config/platform.demo.yaml을 찾을 수 없습니다")


def find_fake_tools() -> Path:
    for c in (HERE / "fake_tools", PKG_ROOT / "backend" / "tests" / "fake_tools"):
        if (c / "fake_hw").is_file():
            return c
    raise SystemExit("가짜 도구(fake_tools)를 찾을 수 없습니다 — 저장소 또는 오프라인 묶음에서 실행하세요")


def move_to_backup(root: Path, path: Path) -> None:
    """사용자 산출물은 삭제하지 않고 <root>/_backup/<UTC>/ 로 옮긴다."""
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = root / "_backup" / stamp
    dest.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dest / path.name))


# ---------------------------------------------------------------------------
# 가짜 도구 설치
# ---------------------------------------------------------------------------


def _windows_exe(src_text: str, name: str, dest_dir: Path) -> Path:
    """pip 내장 distlib 런처로 name.exe 를 만든다(pip 콘솔 스크립트와 같은 방식: 런처 + #!python + zip(__main__.py))."""
    from pip._vendor.distlib.scripts import ScriptMaker  # pip은 venv에 항상 있다

    staging = dest_dir / "_src"
    staging.mkdir(parents=True, exist_ok=True)
    src = staging / name
    src.write_text(src_text, encoding="utf-8")
    maker = ScriptMaker(str(staging), str(dest_dir))  # source_dir 필수(None이면 경로 결합 실패)
    maker.executable = sys.executable
    maker.variants = {""}
    maker.clobber = True
    maker.add_launchers = True
    made = maker.make(name)
    exe = dest_dir / f"{name}.exe"
    if not exe.is_file():
        raise SystemExit(f"가짜 도구 실행 파일을 만들지 못했습니다: {name} ({made})")
    return exe


def install_tools(src_dir: Path, dest_dir: Path) -> dict[str, str]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for name in TOOLS:
        lines = (src_dir / name).read_text(encoding="utf-8").splitlines(keepends=True)
        body = "".join(lines[1:]) if lines and lines[0].startswith("#!") else "".join(lines)
        if os.name == "nt":
            out[name] = str(_windows_exe("#!python\n" + DELAY_PROLOGUE + body, name, dest_dir))
        else:
            dst = dest_dir / name
            dst.write_text(f"#!{sys.executable}\n" + DELAY_PROLOGUE + body, encoding="utf-8")
            dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            out[name] = str(dst)
    return out


# ---------------------------------------------------------------------------
# 가짜 원본 반입 자원(resources.*) — 실제 원본 대신 형식만 흉내
# ---------------------------------------------------------------------------

DOE_TYPES = {
    "FullFact": {"value": "TYPE_FULLFACT", "default_runs": 4, "runs_editable": False, "fields": []},
    "FracFact": {"value": "TYPE_FRACFACT", "default_runs": 4, "runs_editable": False,
                 "fields": [{"key": "RESOLUTION", "label": "Resolution", "type": "combo", "items": ["3", "4", "5"], "default": "3"}]},
    "LatinHyperCube": {"value": "TYPE_LATINHYPERCUBE", "default_runs": 5, "runs_editable": True,
                       "fields": [{"key": "RANDOM_SEED", "label": "Random Seed", "type": "int", "default": 1, "min": 0, "max": 10000}]},
    "Sobol": {"value": "TYPE_SOBOL", "default_runs": 5, "runs_editable": True, "fields": [
        {"key": "SEQUENCE_OFFSET", "label": "Sequence Offset", "type": "int", "default": 1, "min": 0, "max": 999999},
        {"key": "SCRAMBLE", "label": "Scramble", "type": "bool", "default": False},
        {"key": "SEED", "label": "Seed", "type": "int", "default": 0, "min": 0, "max": 999999}]},
}
LAUNCHER_TEXT = """# Generated launcher; the core is a compiled extension.
# 시연용 가짜 런처(원본 BATCHRUN_*.py 형식). 플랫폼은 이 파일을 실행·import하지 않는다.
import importlib
import pathlib
import sys

script_dir = pathlib.Path(__file__).resolve().parent if '__file__' in globals() else pathlib.Path.cwd().resolve()
sys.path.insert(0, str(script_dir))
importlib.import_module('{core}')
"""
LAUNCHERS = (("BATCHRUN_get_parameter_from_cad.py", "get_parameter_from_cad_core"),
             ("BATCHRUN_hst_gen_radioss_input.py", "hst_gen_radioss_core"),
             ("BATCHRUN_hst_physicsai_optimization.py", "hst_physicsai_optimization_core"))
SIMLAB_TPL_TEMPLATE = """\ufeff
{parameter(var_1, "OLD_PARAM", 1, 0, 2)}
# 시연용 tpl 템플릿(원본 TEMAPLATE_simlab_parametered_mesh.tpl 구조 흉내)
#***************************************************************
import simlab
dir_file_prt = r"C:/old/place/old_part.prt"
xml = '''
<Parameters Value="">
   <paramitem Name="OLD_PARAM" NewValue="{var_1, %3i}" Value="1"/>
</Parameters>
'''


simlab.run(xml)
"""


def _write_if_missing(path: Path, data: str | bytes) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8")


def make_resources(res: Path) -> None:
    br, pd = res / "BATCHRUN", res / "BUILD_PYD"
    for script, core in LAUNCHERS:
        _write_if_missing(br / script, LAUNCHER_TEXT.replace("{core}", core))
        _write_if_missing(pd / f"{core}.cp313-win_amd64.pyd", b"FAKE-PYD-NOT-LOADABLE " + core.encode())
    for n in ("BATCHRUN_create_include_node_elem.tcl", "BATCHRUN_preview_h3d.tcl", "BATCHRUN_preview_hg.tcl",
              "BATCHRUN_curate_hg.tcl", "H3D_StaticMinMax_to_CSV_FAST.tcl", "BATCHRUN_preview_pred_h3d.tcl"):
        _write_if_missing(br / n, f"# 시연용 가짜 {n}\n")
    _write_if_missing(res / "DATA" / "DATA_doe_design_type.json", json.dumps(DOE_TYPES, ensure_ascii=False, indent=1))
    _write_if_missing(res / "TEMPLATE" / "TEMAPLATE_simlab_parametered_mesh.tpl", SIMLAB_TPL_TEMPLATE)


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def render_config(template: str, values: dict[str, str]) -> str:
    lines = template.splitlines(keepends=True)
    while lines and (lines[0].startswith("#") or not lines[0].strip()):
        lines.pop(0)  # 템플릿 설명 머리말은 빼고 생성 표시로 바꾼다
    out = ("# PhysicsAI 시연 모드 설정 — deploy/demo/demo_setup.py init 이 config/platform.demo.yaml 에서 생성.\n"
           "# 시연 전용(demo.enabled=true). 운영 설정으로 쓰지 않는다.\n\n") + "".join(lines)
    for k, v in values.items():
        out = out.replace("{{" + k + "}}", v)
    left = re.findall(r"\{\{[A-Z_]+\}\}", out)
    if left:
        raise SystemExit(f"설정 템플릿 자리 채우기 실패: {sorted(set(left))}")
    return out


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    if UNSAFE.search(str(root)):
        raise SystemExit(f"시연 폴더 경로에 공백·특수문자를 쓸 수 없습니다: {root}")
    for d in ("ai_root", "import", "spdm", "state", "config", "logs"):
        (root / d).mkdir(parents=True, exist_ok=True)
    tools = install_tools(find_fake_tools(), root / "tools")
    make_resources(root / "resources")
    frontend = ""
    if args.frontend:
        fr = Path(args.frontend).resolve()
        if not (fr / "index.html").is_file():
            raise SystemExit(f"프런트 빌드 폴더에 index.html이 없습니다: {fr}")
        frontend = fwd(fr)
    text = render_config(find_template().read_text(encoding="utf-8"), {
        "DEMO_ROOT": fwd(root), "TOOL_EXT": ".exe" if os.name == "nt" else "", "PORT": str(int(args.port)),
        "FRONTEND_ROOT": frontend,
    })
    cfg = root / "config" / "platform.yaml"
    if cfg.is_file() and cfg.read_text(encoding="utf-8") != text:
        move_to_backup(root, cfg)
        _log(f"기존 설정을 _backup으로 옮겼습니다: {cfg}")
    if not cfg.is_file():
        cfg.write_text(text, encoding="utf-8")
    sys.path[:0] = [str(PKG_ROOT / "backend"), str(PKG_ROOT / "worker")]
    try:
        from physicsai_core.config import load_config

        lc = load_config(str(cfg), environ={})
        if not lc.ok:
            raise SystemExit("시연 설정 검증 실패: " + "; ".join(f"{i.key}: {i.message}" for i in lc.issues))
    except ImportError:
        _log("physicsai_core를 찾지 못해 설정 검증을 건너뜁니다(백엔드 기동 시 검증)")
    _log(f"설정: {cfg}")
    print(json.dumps({"config": str(cfg), "ai_root": str(root / "ai_root"), "tools": tools}, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------------------
# seed: 시연 Study + 샘플 데이터
# ---------------------------------------------------------------------------


def _api(url: str, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url.rstrip("/") + "/physicsai/api" + path, data=data, method=method)
    req.add_header("Authorization", f"Bearer {POWER_TOKEN}")
    req.add_header("X-PhysicsAI-Request", "1")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - 127.0.0.1 시연 백엔드
            return r.status, json.loads(r.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "null")


def write_samples(root: Path, sroot: Path) -> dict[str, str]:
    """①~⑤ 시연 샘플. 있는 파일은 건드리지 않는다."""
    inbox = sroot / "00_inbox"
    cad = inbox / "cad" / "demo_bracket.prt"
    _write_if_missing(cad, b"FAKE-PRT " * 64)
    assem = inbox / "radioss_assem"
    _write_if_missing(assem / "drop_0000.rad", "#include eps_mesh_1.inc\n/BEGIN\n")
    _write_if_missing(assem / "drop_0001.rad", "/ENGINE\n/RUN/drop/1\n")
    _write_if_missing(assem / "material.inc", "/MAT/PLAS_JOHNS/1\n")
    # ①-5 결과 가져오기용(PBS 대신): run__00001 ~ run__00010
    results = root / "import" / "hpc_results"
    for k in range(1, 11):
        rk = results / f"run__{k:05d}"
        _write_if_missing(rk / "drop_0000.out", f"fake radioss out {k}\n")
        _write_if_missing(rk / "drop_A001.h3d", b"H3D-FAKE" + bytes([k]) * 256)
        _write_if_missing(rk / "drop_T01", f"T01 fake {k}\n")
    # ③-4 모델 등록용(학습은 플랫폼 밖 — 결과 폴더만)
    model = root / "import" / "trained_model"
    _write_if_missing(model / "demo_bracket_TNS.psmdl", os.urandom(4096))
    _write_if_missing(model / "settings.pscfg", b"\x80\x04FAKE-PICKLE-NOT-OPENED")
    _write_if_missing(model / "train.log", "start\n" + "\n".join(
        f"epoch= {e:3d}/  40  loss={50.0 / e:.5e}" for e in range(1, 41)) + "\nend\n")
    # ④ 파라미터 세트 폴더(1차 방식) — ① 결과로 만드는 대신 쓸 수 있는 예시
    ps = inbox / "params_demo"
    _write_if_missing(ps / "cad" / "demo_bracket.x_t", "FAKE CAD\n")
    _write_if_missing(ps / "simlab_parametered_mesh.tpl", (
        '\ufeff{parameter(var_1, "THK_1", 3.0, 2.0, 5.0)}\n{parameter(var_2, "RIB_H", 12.5, 10.0, 15.0)}\n'
        "#***************************************************************\n"
        'dir_file_prt = r"./demo_bracket.x_t"\nthickness = {var_1, %8.4f}\n'
        '<paramitem Name="RIB_H" NewValue="{var_2, %8.4f}" Value="12.5"/>\n'))
    _write_if_missing(ps / "radioss_assem" / "drop_0000.rad", "#include eps_mesh_1.inc\n")
    _write_if_missing(ps / "radioss_assem" / "drop_0001.rad", "/ENGINE\n")
    _write_if_missing(ps / "parameters.json", json.dumps({"schema_version": 1, "unit_system": "mm-ton-s", "parameters": [
        {"name": "THK_1", "nominal": 3.0, "min": 2.0, "max": 5.0, "unit": "mm"},
        {"name": "RIB_H", "nominal": 12.5, "min": 10.0, "max": 15.0, "unit": "mm"}]}, ensure_ascii=False, indent=1))
    _write_if_missing(ps / "responses.json", json.dumps({"responses": [
        {"name": "MaxStress", "unit": "MPa", "spec": {"type": "max"}}, {"name": "Disp", "unit": "mm", "spec": {}}]}))
    rows = ["run_key,THK_1,RIB_H,resp:MaxStress,resp:Disp"] + [
        f"run_{i:04d},{2.0 + i * 0.6:.1f},{10.0 + i:.1f},{100 + i * 7},{1.5 + i * 0.4:.2f}" for i in range(6)]
    _write_if_missing(ps / "samples.csv", "\ufeff" + "\n".join(rows) + "\n")
    return {"cad": str(cad), "radioss_assem": str(assem), "results": str(results), "model": str(model), "param_set": str(ps)}


def cmd_seed(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    code, studies = _api(args.url, "GET", f"/studies?project_id={PROJECT_ID}")
    if code != 200:
        raise SystemExit(f"Study 목록 조회 실패({code}): {studies} — 백엔드가 시연 설정으로 떠 있는지 확인하세요")
    sid = next((s["id"] for s in studies if s.get("folder_name") == STUDY_FOLDER), None)  # type: ignore[union-attr]
    if sid is None:
        code, body = _api(args.url, "POST", "/studies", {"project_id": PROJECT_ID, "folder_name": STUDY_FOLDER, "title": STUDY_TITLE})
        if code != 201:
            raise SystemExit(f"시연 Study 생성 실패({code}): {body}")
        sid = body["id"]  # type: ignore[index]
        _log(f"시연 Study 생성: {STUDY_TITLE} ({STUDY_FOLDER})")
    else:
        _log(f"시연 Study 있음: {STUDY_FOLDER}")
    paths = write_samples(root, root / "ai_root" / STUDY_FOLDER)
    print(json.dumps({"study_id": sid, **paths}, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------------------
# 시연 전용 PostgreSQL(db-up / db-down)
# ---------------------------------------------------------------------------

DB_NAME = "physicsai_demo"


def _pg(bin_dir: str, name: str) -> str:
    exe = Path(bin_dir) / (name + (".exe" if os.name == "nt" else ""))
    if not exe.is_file():
        raise SystemExit(f"PostgreSQL 실행 파일이 없습니다: {exe} (--pg-bin 확인)")
    return str(exe)


def _run(argv: list[str], **kw) -> subprocess.CompletedProcess:
    # pg_ctl이 띄운 서버가 파이프를 물고 있지 않도록 출력은 DEVNULL(로그는 -l 파일)
    return subprocess.run(argv, stdin=subprocess.DEVNULL, **kw)


def cmd_db_up(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    data = root / "pgdata"
    (root / "logs").mkdir(parents=True, exist_ok=True)
    (root / "state").mkdir(parents=True, exist_ok=True)
    port = int(args.pg_port)
    if not (data / "PG_VERSION").is_file():
        _log(f"시연 PostgreSQL 클러스터 생성: {data}")
        r = _run([_pg(args.pg_bin, "initdb"), "-D", str(data), "-U", "postgres", "-A", "trust", "-E", "UTF8", "--no-locale"],
                 stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if r.returncode != 0:
            raise SystemExit(f"initdb 실패: {r.stderr[-2000:]}")
    st = _run([_pg(args.pg_bin, "pg_ctl"), "-D", str(data), "status"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if st.returncode != 0:
        _log(f"시연 PostgreSQL 시작: 127.0.0.1:{port}")
        r = _run([_pg(args.pg_bin, "pg_ctl"), "-D", str(data), "-l", str(root / "logs" / "postgres.log"), "-w", "-o",
                  f"-p {port} -c listen_addresses=127.0.0.1" + ("" if os.name == "nt" else " -c unix_socket_directories=''"),
                  "start"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode != 0:
            raise SystemExit(f"PostgreSQL 시작 실패 — {root / 'logs' / 'postgres.log'} 확인(포트 {port} 사용 중일 수 있음)")
    psql = [_pg(args.pg_bin, "psql"), "-h", "127.0.0.1", "-p", str(port), "-U", "postgres", "-d", "postgres", "-v", "ON_ERROR_STOP=1", "-tAc"]
    has = _run([*psql, f"SELECT 1 FROM pg_database WHERE datname = '{DB_NAME}'"], capture_output=True, text=True)
    if has.returncode != 0:
        raise SystemExit(f"PostgreSQL 접속 실패: {has.stderr[-1000:]}")
    if has.stdout.strip() != "1":
        r = _run([*psql, f'CREATE DATABASE "{DB_NAME}"'], capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"DB 생성 실패: {r.stderr[-1000:]}")
    url = f"postgresql+psycopg://postgres@127.0.0.1:{port}/{DB_NAME}"  # 비밀번호 없음(trust, 127.0.0.1 전용)
    (root / "state" / "demo-db.json").write_text(json.dumps({"pg_bin": str(Path(args.pg_bin).resolve()), "data": str(data),
                                                              "port": port, "url": url}), encoding="utf-8")
    print(json.dumps({"database_url": url}))
    return 0


def cmd_db_down(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    f = root / "state" / "demo-db.json"
    if not f.is_file():
        _log("시연 PostgreSQL 정보가 없습니다(db-up을 쓰지 않음)")
        return 0
    info = json.loads(f.read_text(encoding="utf-8"))
    r = _run([_pg(info["pg_bin"], "pg_ctl"), "-D", info["data"], "-m", "fast", "-w", "stop"],
             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _log("시연 PostgreSQL 중지" if r.returncode == 0 else "시연 PostgreSQL이 이미 멈춰 있습니다")
    return 0


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
        env["PYTHONPATH"] = os.pathsep.join([str(PKG_ROOT / "backend"), str(PKG_ROOT / "worker")] +
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
    be = _spawn([sys.executable, "-m", "physicsai_api.serve"], env, logs / "backend.log", root)
    procs["backend"] = {"pid": be.pid, "create_time": psutil.Process(be.pid).create_time()}
    state.write_text(json.dumps(procs), encoding="utf-8")
    end = time.time() + float(args.timeout)
    while not _health(port):
        if be.poll() is not None or time.time() > end:
            raise SystemExit(f"백엔드 기동 실패 — {logs / 'backend.log'} 확인")
        time.sleep(0.5)
    _log(f"백엔드 기동: http://127.0.0.1:{port}/")
    seed = argparse.Namespace(root=str(root), url=f"http://127.0.0.1:{port}")
    cmd_seed(seed)
    wk = _spawn([sys.executable, "-m", "physicsai_worker", "--config", str(cfg)], env, logs / "worker.log", root)
    procs["worker"] = {"pid": wk.pid, "create_time": psutil.Process(wk.pid).create_time()}
    state.write_text(json.dumps(procs), encoding="utf-8")
    time.sleep(1.0)
    if wk.poll() is not None:
        raise SystemExit(f"워커 기동 실패 — {logs / 'worker.log'} 확인")
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
