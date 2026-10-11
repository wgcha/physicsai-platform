"""패키지 시험용 최소 가짜 PBS(backend/tests/fake_tools의 fake_qsub·fake_qstat·fake_qdel 최소 사본).

사용: python fake_pbs.py qsub|qstat|qdel ... — 상태 파일은 FAKE_PBS_STATE, 모드는 FAKE_TOOL_MODE_PBS
(ok | submit_fail | not_found | unknown | cancel_fail). qstat은 id별 호출 횟수로 Q → R → F(+Exit_status 0).
"""
import json
import os
import sys

tool = sys.argv[1]
args = sys.argv[2:]
mode = os.environ.get("FAKE_TOOL_MODE_PBS") or "ok"
state = os.environ["FAKE_PBS_STATE"]
st = json.load(open(state, encoding="utf-8")) if os.path.exists(state) else {}
st.setdefault("jobs", {})
st.setdefault("next", 12345)
st.setdefault("calls", []).append([tool, *args])
code = 0
if tool == "qsub":
    if mode == "submit_fail":
        print("qsub: Unauthorized Request", file=sys.stderr)
        code = 1
    else:
        jid = f"{st['next']}.pbs01"
        st["next"] += 1
        st["jobs"][jid] = {"polls": 0}
        print(jid)
elif tool == "qstat":
    jid = args[-1]
    job = st["jobs"].setdefault(jid, {"polls": 0})
    job["polls"] += 1
    if mode == "not_found":
        print(f"qstat: Unknown Job Id {jid}", file=sys.stderr)
        code = 153
    elif mode == "unknown":
        print("garbage output")
    else:
        n = job["polls"]
        s = "Q" if n == 1 else ("R" if n == 2 else "F")
        print(f"Job Id: {jid}\n    job_state = {s}")
        if s == "F":
            print("    Exit_status = 0")
elif tool == "qdel":
    if mode == "cancel_fail":
        print("qdel: Server unreachable", file=sys.stderr)
        code = 1
json.dump(st, open(state, "w", encoding="utf-8"))
sys.exit(code)
