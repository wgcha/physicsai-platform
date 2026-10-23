"""0024_contour3d_field — 결과 3D 컨투어 현장 보정: artifacts.kind에 CONTOUR3D_DISP·CONTOUR3D_LOD 추가(contour3d-field.md §5.6, C3F-6·C3F-8). 명시적 DDL(B14).

운영 DB의 `ck_artifacts_kind` CHECK가 kind를 열거하므로(0017이 CONTOUR3D_GLB·FRAMES·MANIFEST까지 허용) 새 kind 2개를 넣으려면 제약을 바꿔야 한다.
테이블·열 추가는 없다 — 변위·LOD 산출물 id는 캐시 행이 아니라 같은 작업의 artifacts에서 kind로 조회한다.

- 업그레이드: ck_artifacts_kind를 기존 24개 + CONTOUR3D_DISP·CONTOUR3D_LOD로 교체(행 데이터 무변경)
- 다운그레이드: 새 kind 산출물이 하나라도 있으면 거부(데이터 보호, 0017·0023 선례), 없으면 기존 제약으로 되돌림

Revision ID: 0024_contour3d_field
Revises: 0023_doe_methods
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_contour3d_field"
down_revision = "0023_doe_methods"
branch_labels = None
depends_on = None

OLD_KINDS = (
    "'PREVIEW_JSON','PREVIEW_IMAGE','CURVE_JSON','RESPONSE_TABLE','SCORE_FILE','PACKAGE_COMMANDS','SPLIT_JSON',"
    "'CURATION_CFG','FILE_LIST','DOE_SAMPLES','RUN_CONFIG','OPT_SUMMARY','OPT_FILE','CONTOUR_IMAGE','CONTOUR_VIDEO','FEATURE_PNG',"
    "'GEOM_VIEW_GLB','GEOM_VIEW_MANIFEST','GEOM_PREVIEW_GLB','GEOM_PREVIEW_FE_GLB','GEOM_PREVIEW_MANIFEST',"
    "'CONTOUR3D_GLB','CONTOUR3D_FRAMES','CONTOUR3D_MANIFEST'"
)
NEW_KINDS = "'CONTOUR3D_DISP','CONTOUR3D_LOD'"


def upgrade() -> None:
    op.drop_constraint("ck_artifacts_kind", "artifacts", type_="check")
    op.create_check_constraint("ck_artifacts_kind", "artifacts", f"kind IN ({OLD_KINDS},{NEW_KINDS})")


def downgrade() -> None:
    n = op.get_bind().execute(sa.text(f"SELECT count(*) FROM artifacts WHERE kind IN ({NEW_KINDS})")).scalar()
    if n:
        raise RuntimeError(f"3D 컨투어 변위·LOD 산출물 {n}개가 있어 0024를 되돌릴 수 없습니다(데이터 보호)")
    op.drop_constraint("ck_artifacts_kind", "artifacts", type_="check")
    op.create_check_constraint("ck_artifacts_kind", "artifacts", f"kind IN ({OLD_KINDS})")
