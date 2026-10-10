"""③-2 PACKAGE_EXPORT(§8.5)."""

from __future__ import annotations

import os
from typing import Any

from physicsai_core.db.repositories import datasets as datasets_repo
from physicsai_core.errors import StepFailure
from physicsai_core.fileutil import copy_file, write_text

COMMANDS_TXT = """# PhysicsAI 학습 명령 예시 (HPC에서 직접 실행)
# 단위계: mm-ton-s. 이 폴더의 dataset_train.psdata는 학습용입니다(평가용 홀드아웃 제외).
edspy --physicsai --train <MODEL_NAME>.psmdl --dataset dataset_train.psdata --spec <SETTINGS>.pscfg > train.log 2>&1
# 전이학습:
edspy --physicsai --train <MODEL_NAME>.psmdl --dataset dataset_train.psdata --spec <SETTINGS>.pscfg --pretrained-model <PRETRAINED>.psmdl > train.log 2>&1
# 학습이 끝나면 .psmdl, 사용한 .pscfg, train.log를 한 폴더에 모아 플랫폼 ③-4 "모델 등록"에서 그 폴더 경로를 지정하세요.
# 로그의 loss 줄 예: "epoch=   1/1500  loss=1.03956e+02"
"""

REGISTER_README = """PhysicsAI 모델 등록(③-4) 폴더 형식
================================

HPC 학습이 끝나면 아래 파일을 한 폴더에 모으고, 플랫폼 ③-4 "모델 등록"에서 그 폴더 경로를 지정하세요.
폴더는 AI 루트 또는 관리자가 허용한 가져오기 루트 아래에 있어야 합니다(경로에 공백·특수문자 금지).

- <MODEL_NAME>.psmdl : 정확히 1개 (필수)
- <SETTINGS>.pscfg  : 정확히 1개 (필수, 플랫폼은 경로·해시만 기록하고 열지 않습니다)
- 학습 로그(*.log 또는 *.txt) : 0~1개 (여러 개면 등록 화면에서 선택)

하위 폴더는 보지 않습니다. 등록하면 파일이 Study 폴더로 복사되므로 원본 폴더는 지워도 됩니다.
로그 형식을 인식하지 못해도 등록은 성공하며 화면에 "로그 형식 미확인"으로 표시됩니다.
"""


def _paths(ctx: Any) -> tuple[str, str, str]:
    ds_id = ctx.params["dataset_id"]
    return ds_id, ctx.abs(f"03_dataset/{ds_id}"), ctx.abs(f"03_package/{ds_id}")


def pkg_copy(ctx: Any) -> None:
    ds_id, D, K = _paths(ctx)
    src = os.path.join(D, "train", "dataset.psdata")
    if not os.path.isfile(src):
        raise StepFailure("INPUT_INVALID", "학습용 dataset.psdata가 없습니다")
    dst = os.path.join(K, "dataset_train.psdata")
    os.makedirs(K, exist_ok=True)
    ctx.backup([dst])
    total = os.path.getsize(src) or 1
    linked = False
    if ctx.settings.package.link_mode == "hardlink_or_copy":
        try:
            os.link(src, dst)
            linked = True
            ctx.log("하드링크로 연결했습니다")
        except OSError as exc:
            ctx.log(f"하드링크 실패({exc}) → 복사합니다")
    if not linked:
        copy_file(src, dst, progress=lambda n: ctx.progress(100.0 * n / total, f"복사 {n}/{total} bytes"),
                  checkpoint=ctx.checkpoint)
    ctx.add_output(dst)
    ctx.patch_result({"dataset_id": ds_id, "linked": linked})


def pkg_text(ctx: Any) -> None:
    ds_id, _D, K = _paths(ctx)
    cmd, readme = os.path.join(K, "COMMANDS.txt"), os.path.join(K, "REGISTER_README.txt")
    ctx.backup([cmd, readme])
    write_text(cmd, COMMANDS_TXT)
    write_text(readme, REGISTER_README)
    package_rel = f"03_package/{ds_id}/"
    ctx.ex.db(lambda c: datasets_repo.set_values(c, ds_id, package_rel=package_rel))
    aid = ctx.register_artifact("PACKAGE_COMMANDS", cmd)
    ctx.patch_result({"package_rel": package_rel, "commands_artifact_id": aid})


HANDLERS = {("PACKAGE_EXPORT", "PKG_COPY"): pkg_copy, ("PACKAGE_EXPORT", "PKG_TEXT"): pkg_text}
