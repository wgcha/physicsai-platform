"""BATCHRUN 런처 준비(phase2 §4.2). 원본 __sync_python_batch_to_workspace(1_gui_create_tpl_file.py:159-189)·
_copy_python_batch(4_OPTIMIZATION/FUNC/1_physicsai_opti.py:135-158) 재구현.

플랫폼 프로세스는 런처를 실행하거나 pyd를 import하지 않는다. 파일을 그대로 복사만 한다(Altair 도구의 Python이 실행).
"""

from __future__ import annotations

import glob
import os
from typing import Any

from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file, sha256_file

LAUNCHER_MARK = "# Generated launcher;"


def is_compiled_launcher(script_path: str) -> bool:
    with open(script_path, encoding="utf-8-sig") as fh:
        return fh.readline().startswith(LAUNCHER_MARK)


def find_pyd(pyd_dir: str, core: str) -> list[str]:
    if not pyd_dir:
        return []
    return sorted(p for p in glob.glob(os.path.join(pyd_dir, f"{core}*.pyd")) if os.path.isfile(p))


def check_launcher(settings: Any, key: str) -> dict[str, Any]:
    """환경 점검·준비 공용: {script, compiled, pyd:[…], problem}."""
    res = settings.resources
    lc = res.launchers.get(key)
    if lc is None:
        return {"problem": f"resources.launchers.{key} 미설정"}
    if not res.batchrun_dir:
        return {"problem": "resources.batchrun_dir 미설정"}
    script = os.path.join(res.batchrun_dir, lc.script)
    if not os.path.isfile(script):
        return {"script": script, "problem": f"런처 파일이 없습니다: {script}"}
    compiled = is_compiled_launcher(script)
    out: dict[str, Any] = {"script": script, "compiled": compiled, "core": lc.core, "pyd": []}
    if compiled:
        pyd = find_pyd(res.pyd_dir, lc.core)
        out["pyd"] = pyd
        if len(pyd) != 1:
            out["problem"] = f"pyd가 정확히 1개가 아닙니다: {len(pyd)}개 ({lc.core}*.pyd)"
    return out


def stage_launcher(ctx: Any, key: str, work_dir: str) -> str:
    """런처(+compiled면 pyd 1개)를 작업 폴더에 같은 이름으로 복사. 작업 폴더 안 런처 절대경로를 돌려준다."""
    info = check_launcher(ctx.settings, key)
    if info.get("problem"):
        raise StepFailure("RESOURCE_MISSING", info["problem"])
    os.makedirs(work_dir, exist_ok=True)
    copies = [info["script"], *info["pyd"]]
    dsts = [os.path.join(work_dir, os.path.basename(p)) for p in copies]
    ctx.backup([d for d in dsts if os.path.lexists(d)])
    for src, dst in zip(copies, dsts):
        copy_file(src, dst, checkpoint=ctx.checkpoint)
        ctx.outputs["files"].append({"rel": ctx.rel(dst), "size": os.path.getsize(dst), "sha256": sha256_file(dst)})
    ctx.log(f"런처 준비: {os.path.basename(info['script'])}" + (f" + {os.path.basename(info['pyd'][0])}" if info["pyd"] else ""))
    return dsts[0]
