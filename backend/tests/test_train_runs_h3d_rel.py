"""geometry-view GV-C3: GET /train-does/{doe_id}/runs의 run별 결과 h3d 상대 경로 `h3d_rel`.

수집 전·h3d 없음 → null, 수집됨 → Study 기준 상대 경로(결과 폴더 하위, `_backup` 제외, 여러 개면 정렬 첫 번째),
결과 폴더가 Study 밖이면 null. 그 경로를 3D 컨투어 SOLVER_H3D `{study_id, h3d_rel}`로 그대로 쓸 수 있다(.h3d).
"""

from __future__ import annotations

from helpers_stage1 import P, _ready_doe
from physicsai_core.db.repositories import train as train_repo
from physicsai_test_support import API


def test_train_runs_h3d_rel(p2_env, engine):
    c, mk, ai, _lc, _d = p2_env
    name = "H3DREL"
    sid, doe_id = _ready_doe(c, mk(), ai, name, num_runs=4)
    runs = c.get(f"{API}/train-does/{doe_id}/runs", headers=P).json()
    assert len(runs) == 4 and all(r["h3d_rel"] is None for r in runs)
    k0, k1, k2, k3 = [r["run_key"] for r in runs]
    base = f"01_train/results/{doe_id}"
    for rk in (k0, k1, k2):
        (ai / name / base / rk / "_backup").mkdir(parents=True)
    (ai / name / base / k0 / "zz_A001.h3d").write_bytes(b"h")
    (ai / name / base / k0 / "sub").mkdir()
    (ai / name / base / k0 / "sub" / "a.h3d").write_bytes(b"h")
    (ai / name / base / k0 / "_backup" / "0.h3d").write_bytes(b"old")
    (ai / name / base / k1 / "_backup" / "0.h3d").write_bytes(b"old")  # _backup만 → null
    with engine.begin() as conn:
        train_repo.set_run(conn, doe_id, k0, state="COLLECTED", result_rel=f"{base}/{k0}/", result_summary={"h3d": 2, "t01": 0, "files": 2, "total_bytes": 2})
        train_repo.set_run(conn, doe_id, k1, state="COLLECTED", result_rel=f"{base}/{k1}/", result_summary={"h3d": 1, "t01": 0, "files": 1, "total_bytes": 3})
        train_repo.set_run(conn, doe_id, k2, state="COLLECTED", result_rel=f"{base}/{k2}/", result_summary={"h3d": 0, "t01": 0, "files": 0, "total_bytes": 0})
        train_repo.set_run(conn, doe_id, k3, state="COLLECTED", result_rel="../../outside/", result_summary={"h3d": 1, "t01": 0, "files": 1, "total_bytes": 1})
    got = {r["run_key"]: r["h3d_rel"] for r in c.get(f"{API}/train-does/{doe_id}/runs", headers=P).json()}
    assert got == {k0: f"{base}/{k0}/sub/a.h3d", k1: None, k2: None, k3: None}
    assert (ai / name / got[k0]).is_file() and got[k0].endswith(".h3d")
