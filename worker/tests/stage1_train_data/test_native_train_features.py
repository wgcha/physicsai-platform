"""① native 추출 피처 조회 `GET /studies/{id}/train/features`(geometry-engine.md §7.3.1): 종류·범위·그룹·하이라이트 PNG artifact id,
추출 전·altair는 409."""

from __future__ import annotations

from helpers_stage1 import study
from physicsai_test_support import API, H

from .test_native_doe import _extract

P = H("tok-power")


def test_train_features_with_png_ids(p2_native):
    c, mk, ai, _lc, _d = p2_native
    w = mk()
    sid = study(c, "tf1")
    r = c.get(f"{API}/studies/{sid}/train/features", headers=P)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NATIVE_PREP_MISSING"
    _extract(c, w, sid, ai, "tf1")
    f = c.get(f"{API}/studies/{sid}/train/features", headers=P).json()
    by = {x["name"]: x for x in f["features"]}
    assert set(by) == {"A_THK_1", "A_THK_2", "B_RIB_H_1", "C_HOLE_R_1"} and by["B_RIB_H_1"]["type"] == "RIB_HEIGHT"
    assert all(x["png_artifact_id"] for x in f["features"]) and f["groups"][0]["members"] == ["A_THK_1", "A_THK_2"]
    m = c.get(f"{API}/artifacts/{by['A_THK_1']['png_artifact_id']}/media", headers=P)
    assert m.status_code == 200 and m.content.startswith(b"\x89PNG")
