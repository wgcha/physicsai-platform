"""시험 공용 입력 폴더 생성 도우미: H3D 트리, 모델 폴더, ④ 파라미터 세트 폴더."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

# ---------------------------------------------------------------------------
# 입력 폴더 생성 도우미
# ---------------------------------------------------------------------------


def make_h3d_tree(root: Path, n: int = 10, nested: bool = True) -> Path:
    inp = root / "00_inbox" / "h3d"
    for i in range(n):
        d = inp / f"run_{i:04d}" if nested else inp
        d.mkdir(parents=True, exist_ok=True)
        (d / f"result_{i:04d}.h3d").write_bytes(b"H3D" + bytes([i]))
    return inp


def make_model_folder(root: Path, name: str = "cushion_TNS", log: str | None = "default", extra_log: bool = False) -> Path:
    d = root / f"model_{uuid.uuid4().hex[:6]}"
    d.mkdir(parents=True)
    (d / f"{name}.psmdl").write_bytes(os.urandom(2048))
    (d / "settings.pscfg").write_bytes(b"\x80\x04pickle-not-opened")
    if log == "default":
        lines = [f"epoch= {e:3d}/  50  loss={100.0 / e:.5e}" for e in range(1, 51)]
        (d / "train.log").write_text("start\n" + "\n".join(lines) + "\nend\n")
    elif log == "garbage":
        (d / "train.log").write_text("no loss lines here\n")
    if extra_log:
        (d / "other.txt").write_text("x\n")
    return d


TPL_TEXT = """﻿{parameter(var_1, "THK_1", 3.0, 2.0, 5.0)}
{parameter(var_2, "N_RIB", 4, 2, 8)}
#***************************************************************
dir_file_prt = r"./bracket.x_t"
thickness = {var_1, %8.4f}
<paramitem Name="N_RIB" NewValue="{var_2, %3i}" Value="4"/>
"""


def make_param_set_folder(root: Path, *, with_samples: bool = True, with_responses: bool = True,
                          tpl: str = TPL_TEXT, starters: int = 1) -> Path:
    d = root / f"params_{uuid.uuid4().hex[:6]}"
    (d / "cad").mkdir(parents=True)
    (d / "cad" / "bracket.x_t").write_text("CAD")
    (d / "simlab_parametered_mesh.tpl").write_text(tpl, encoding="utf-8")
    (d / "radioss_assem").mkdir()
    for i in range(starters):
        (d / "radioss_assem" / f"model{i}_0000.rad").write_text("#include eps_mesh_1.inc\n")
    (d / "radioss_assem" / "model_0001.rad").write_text("engine\n")
    (d / "radioss_assem" / "eps_mesh_old.inc").write_text("old mesh\n")
    (d / "radioss_assem" / "material.inc").write_text("mat\n")
    (d / "parameters.json").write_text(json.dumps({
        "schema_version": 1, "unit_system": "mm-ton-s",
        "parameters": [
            {"name": "THK_1", "nominal": 3.0, "min": 2.0, "max": 5.0, "unit": "mm"},
            {"name": "N_RIB", "nominal": 4, "min": 2, "max": 8, "unit": ""},
        ],
    }))
    if with_responses:
        (d / "responses.json").write_text(json.dumps({"responses": [
            {"name": "MaxStress", "unit": "MPa", "spec": {"type": "max"}},
            {"name": "Disp", "unit": "mm", "spec": {}},
        ]}))
    if with_samples:
        rows = ["run_key,THK_1,N_RIB" + (",resp:MaxStress,resp:Disp" if with_responses else "")]
        for i, (t, n) in enumerate([(2.0, 2), (3.0, 4), (4.0, 6), (5.0, 8)]):
            rows.append(f"run_{i:04d},{t},{n}" + (f",{100 + i * 10},{1.5 + i}" if with_responses else ""))
        (d / "samples.csv").write_text("﻿" + "\n".join(rows) + "\n", encoding="utf-8")
    return d
