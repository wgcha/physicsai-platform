# S14 영향도 골든 픽스처 생성: numpy·scipy 참조값(PRCC = 순위 변수 잔차의 상관, SRC = z-점수 OLS). 실행: /opt/venv312/bin/python frontend/scripts/gen_influence_golden.py > frontend/src/__tests__/fixtures/influenceGolden.json
import json
import numpy as np
from scipy.stats import rankdata

def prcc(X, y):
    R = np.column_stack([rankdata(c) for c in X.T])
    ry = rankdata(y)
    out = []
    for j in range(X.shape[1]):
        others = np.delete(R, j, axis=1)
        A = np.column_stack([np.ones(len(y)), others])
        ex = R[:, j] - A @ np.linalg.lstsq(A, R[:, j], rcond=None)[0]
        ey = ry - A @ np.linalg.lstsq(A, ry, rcond=None)[0]
        out.append(float(np.corrcoef(ex, ey)[0, 1]))
    return out

def src(X, y):
    Z = (X - X.mean(0)) / X.std(0, ddof=1)
    yz = (y - y.mean()) / y.std(ddof=1)
    A = np.column_stack([np.ones(len(y)), Z])
    beta = np.linalg.lstsq(A, yz, rcond=None)[0]
    res = yz - A @ beta
    r2 = 1 - (res @ res) / (yz @ yz)
    return [float(b) for b in beta[1:]], float(r2)

rng = np.random.default_rng(14)
n = 12
X = rng.uniform(size=(n, 4))
X[:, 2] = np.round(X[:, 2] * 3) / 3          # 동순위(평균 순위) 포함
y = 5 * X[:, 0] - 2 * X[:, 1] + 0.3 * X[:, 2] + 0.5 * rng.normal(size=n)
names = ["A", "B", "C", "D"]
b, r2 = src(X, y)
case1 = {"name": "ties", "names": names, "cols": X.T.round(6).tolist(), "y": y.round(6).tolist()}
# 반올림한 입력으로 다시 계산해 참조값 고정
X1 = np.array(case1["cols"]).T
y1 = np.array(case1["y"])
b, r2 = src(X1, y1)
case1.update({"prcc": prcc(X1, y1), "src": b, "r2": r2})

# 비선형(단조) 응답: PRCC와 SRC가 다르게 나오는 경우, n = 10, p = 2
x = rng.uniform(size=(10, 2))
yy = np.exp(3 * x[:, 0]) - 0.5 * x[:, 1]
case2 = {"name": "monotone", "names": ["P", "Q"], "cols": x.T.round(6).tolist(), "y": yy.round(6).tolist()}
x2 = np.array(case2["cols"]).T; y2 = np.array(case2["y"])
b2, r22 = src(x2, y2)
case2.update({"prcc": prcc(x2, y2), "src": b2, "r2": r22})

# 공선: C = 2A + 1(순위도 같음) → 행렬 특이, PRCC·SRC 모두 계산 불가(numpy: 순위 상관행렬 rank 부족)
a = rng.uniform(size=8); bb = rng.uniform(size=8)
R3 = np.corrcoef(np.column_stack([rankdata(a), rankdata(bb), rankdata((2 * a.round(6) + 1).round(6))]).T)
assert np.linalg.matrix_rank(R3) < 3
case3 = {"name": "collinear", "names": ["A", "B", "C"], "cols": [a.round(6).tolist(), bb.round(6).tolist(), (2 * a.round(6) + 1).round(6).tolist()], "y": (a + 2 * bb + 0.1 * rng.normal(size=8)).round(6).tolist(), "prcc": [None, None, None], "src": [None, None, None], "r2": None}

print(json.dumps({"tolerance": 1e-6, "cases": [case1, case2, case3]}, ensure_ascii=False, indent=1))
