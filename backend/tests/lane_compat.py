"""구 revision(0022 이전)과 head 양쪽에서 쓰는 jobs.lane 값: ck_jobs_lane이 SLOT을 허용하면 SLOT, 아니면 CPU(job-queues.md 0022)."""

LANE_SQL = ("(case when exists(select 1 from pg_constraint where conname='ck_jobs_lane' "
            "and pg_get_constraintdef(oid) like '%SLOT%') then 'SLOT' else 'CPU' end)")
