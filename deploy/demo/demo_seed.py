"""시연 `seed`: 파워 사용자로 시연 Study를 만들고 ①~⑤ 샘플 데이터를 넣는다(있는 파일은 그대로)."""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from demo_common import (
    POWER_TOKEN,
    PROJECT_ID,
    STUDY_FOLDER,
    STUDY_TITLE,
    _log,
    _write_if_missing,
    local_urlopen,
)

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
        with local_urlopen(req, timeout=30) as r:  # 127.0.0.1 시연 백엔드 — 프록시 미사용
            return r.status, json.loads(r.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8") or "null")


def write_samples(root: Path, sroot: Path) -> dict[str, str]:
    """①~⑤ 시연 샘플. 있는 파일은 건드리지 않는다."""
    inbox = sroot / "00_inbox"
    cad = inbox / "cad" / "demo_bracket.prt"
    _write_if_missing(cad, b"FAKE-PRT " * 64)
    assem = inbox / "radioss_assem"
    _write_assem(assem)
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
        'dir_file_prt = r"./demo_bracket.x_t"\ndir_file_export = "EPS_mesh_0000.rad"\nthickness = {var_1, %8.4f}\n'
        '<paramitem Name="RIB_H" NewValue="{var_2, %8.4f}" Value="12.5"/>\n'))
    _write_assem(ps / "radioss_assem")
    _write_if_missing(ps / "parameters.json", json.dumps({"schema_version": 1, "unit_system": "mm-ton-s", "parameters": [
        {"name": "THK_1", "nominal": 3.0, "min": 2.0, "max": 5.0, "unit": "mm"},
        {"name": "RIB_H", "nominal": 12.5, "min": 10.0, "max": 15.0, "unit": "mm"}]}, ensure_ascii=False, indent=1))
    _write_if_missing(ps / "responses.json", json.dumps({"responses": [
        {"name": "MaxStress", "unit": "MPa", "spec": {"type": "max"}}, {"name": "Disp", "unit": "mm", "spec": {}}]}))
    rows = ["run_key,THK_1,RIB_H,resp:MaxStress,resp:Disp"] + [
        f"run_{i:04d},{2.0 + i * 0.6:.1f},{10.0 + i:.1f},{100 + i * 7},{1.5 + i * 0.4:.2f}" for i in range(6)]
    _write_if_missing(ps / "samples.csv", "\ufeff" + "\n".join(rows) + "\n")
    # ④ 준비된 입력 예측(phase3 §11.5)용: 사용자가 준비한 Radioss 입력 폴더(읽기만 — 플랫폼은 복사본으로 예측)
    prepared = root / "import" / "prepared_case"
    _write_if_missing(prepared / "Face_Drop_0000.rad", "#include part_mesh.inc\n#include material.inc\n/BEGIN\n")
    _write_if_missing(prepared / "Face_Drop_0001.rad", "/ENGINE\n/RUN/Face_Drop/1\n")
    _write_if_missing(prepared / "part_mesh.inc", "/NODE\n1 0 0 0\n")
    _write_if_missing(prepared / "material.inc", "/MAT/PLAS_JOHNS/1\n")
    return {"cad": str(cad), "radioss_assem": str(assem), "results": str(results), "model": str(model), "param_set": str(ps),
            "prepared_input": str(prepared)}


def _write_assem(assem: Path) -> None:
    """원본 조립 폴더 형태(phase3 §11.1): starter가 새 메시 include(104_replace_node_elem.inc)를 #include, 기준 include·
    RENUM_INIT.csv·SimLab 메시 사본(EPS_mesh_0000.rad — 복사·starter 셈에서 제외)."""
    _write_if_missing(assem / "drop_0000.rad", "#include 104_replace_node_elem.inc\n#include material.inc\n/BEGIN\n")
    _write_if_missing(assem / "drop_0001.rad", "/ENGINE\n/RUN/drop/1\n")
    _write_if_missing(assem / "material.inc", "/MAT/PLAS_JOHNS/1\n")
    _write_if_missing(assem / "104_replace_node_elem.inc", "/NODE\n3000001 0 0 0\n")
    _write_if_missing(assem / "RENUM_INIT.csv", "part,node_start,elem_start\n1,3000001,3000001\n")
    _write_if_missing(assem / "EPS_mesh_0000.rad", "#RADIOSS STARTER (SimLab mesh)\n")


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
