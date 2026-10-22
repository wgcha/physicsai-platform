"""job-queues.md V-JQ-9: ④ 일괄 예측 파이프라인 — 하위 PREDICT(prepared)가 GPU는 추론만 연달아 쓰고 한 하위의 후처리(CPU)와 다음 하위의 추론이
겹친다. 배치 집계(batch_on_job_end)는 구간 전환(T17)이 있어도 정상. 부모 입력 생성은 실제 가짜 도구, 하위는 지연 핸들러."""

from __future__ import annotations


from queue_support import Pool, Sampler, patch_handlers, wait_all_terminal

ROWS6 = "THK_1\tN_RIB\n" + "".join(f"{2.5 + 0.1 * i:.1f}\t{3 + i % 3}\n" for i in range(6))


def test_v_jq_9_batch_children_pipeline_and_aggregation(predict_env, monkeypatch):
    env = predict_env()
    ps = env.param_set()
    bid, pj = env.make_batch(ps["id"], ROWS6, multi=2)
    assert env.w.run_once_slot() == "SUCCEEDED", env.job(pj)  # 부모(BP_PREP·BP_GEN·BP_ENQUEUE)는 CPU 구간 하나로 끝난다
    kids = [r["predict_job_id"] for r in env.batch(bid)["runs"]]
    assert len(kids) == 6 and all(k for k in kids)
    with env.engine.connect() as c:
        from sqlalchemy import text

        assert {r[0] for r in c.execute(text("select lane from jobs where id = any(:k)"), {"k": kids})} == {"CPU"}  # prepared도 첫 구간은 CPU
    rec = patch_handlers(monkeypatch, {"PR_PREP": 0.05, "EDSPY_PREDICT": 0.3, "CONTOUR_PREVIEW": 0.3, "CONTOUR_CAPTURE": 0.2})
    env.w.available_memory_gb = lambda: 64.0  # 시험 머신 메모리와 무관하게 CPU 수령 문 통과(문 자체는 test_job_queues_flow V-JQ-13)
    smp = Sampler(env.engine)
    smp.start()
    pool = Pool()
    pool.spawn(1, env.w.run_once_gpu, "gpu")
    pool.spawn(3, env.w.run_once_cpu, "cpu")
    try:
        states = wait_all_terminal(env.engine, kids, timeout=60)
    finally:
        pool.stop()
        smp.stop()
    assert set(states.values()) == {"SUCCEEDED"}
    assert smp.max_gpu == 1 and rec.max_active["GPU"] == 1  # 어느 순간에도 GPU 실행 ≤ 1
    for k in kids:
        assert rec.lanes(k) == ["CPU", "GPU", "CPU"]
    # 한 하위의 후처리(CONTOUR_PREVIEW, CPU)와 다른 하위의 추론(EDSPY_PREDICT, GPU)이 겹치는 구간이 존재 = 파이프라인
    overlaps = 0
    for a in kids:
        post = rec.intervals(a, "CONTOUR_PREVIEW")
        for b in kids:
            if a != b:
                gpu = rec.intervals(b, "EDSPY_PREDICT")
                overlaps += max(0.0, min(post[1], gpu[1]) - max(post[0], gpu[0])) > 0.05
    assert overlaps >= 1
    # 배치 집계(종료 훅)는 정상: 6건 모두 끝나 배치 DONE 1회, 완료 알림 1건
    b = env.batch(bid)
    assert b["status"] == "DONE"
    with env.engine.connect() as c:
        from sqlalchemy import text

        assert c.execute(text("select count(*) from notifications where event='PREDICT_BATCH_DONE'")).scalar() == 1
