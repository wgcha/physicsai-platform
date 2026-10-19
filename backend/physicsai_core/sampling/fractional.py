"""2수준 요인 설계 — 부분 요인 생성자 표·Yates 순서·해상도 계산·Plackett–Burman(phase3 §20.5.5·§20.5.6, D3-63).

순수 Python(무작위 없음). 코드값은 −1/+1 정수이고, 값 변환은 `designs.code_to_value`가 한다.
"""

from __future__ import annotations

from itertools import combinations

LETTERS = "ABCDEFGHJKL"  # I는 건너뜀(변수 최대 11개)
MIN_K, MAX_K = 2, 11
FULL_RESOLUTION = 99  # 전체 요인: 교락 없음

# k → (기본 요인 수 r, 생성자 "E=ABC" 목록). r = k이면 전체 2수준 요인(생성자 없음).
# Montgomery 표 8.14 기준. 정의 관계로 해상도를 계산해 검증한다(`resolution_of`, 시험 V3-S15-4).
_G4: dict[int, tuple[int, tuple[str, ...]]] = {
    2: (2, ()), 3: (3, ()),
    4: (3, ("D=ABC",)),
    5: (4, ("E=ABCD",)),
    6: (4, ("E=ABC", "F=BCD")),
    7: (4, ("E=ABC", "F=BCD", "G=ACD")),
    8: (4, ("E=BCD", "F=ACD", "G=ABC", "H=ABD")),
    9: (5, ("F=BCDE", "G=ACDE", "H=ABDE", "J=ABCE")),
    10: (5, ("F=ABCD", "G=ABCE", "H=ABDE", "J=ACDE", "K=BCDE")),
    11: (5, ("F=ABC", "G=BCD", "H=CDE", "J=ACD", "K=ADE", "L=BDE")),
}
_G5: dict[int, tuple[int, tuple[str, ...]]] = {
    2: (2, ()), 3: (3, ()), 4: (4, ()),
    5: (4, ("E=ABCD",)),
    6: (5, ("F=ABCDE",)),
    7: (6, ("G=ABCDEF",)),
    8: (6, ("G=ABCD", "H=ABEF")),
    9: (7, ("H=ACDFG", "J=BCEFG")),
    10: (7, ("H=ABCG", "J=BCDE", "K=ACDF")),
    11: (7, ("H=ABCG", "J=BCDE", "K=ACDF", "L=ABCDEFG")),
}
TABLES = {4: _G4, 5: _G5}


def generator_table(resolution: int) -> dict[int, tuple[int, tuple[str, ...]]]:
    return TABLES[resolution]


def defining_words(generators: tuple[str, ...]) -> set[frozenset[str]]:
    """정의 관계의 모든 단어(생성자 단어의 모든 부분집합 곱 = 대칭차). 빈 집합 제외."""
    base = []
    for g in generators:
        left, right = g.split("=")
        base.append(frozenset(left) ^ frozenset(right))  # I = (left)(right) → 단어
    words: set[frozenset[str]] = set()
    for n in range(1, len(base) + 1):
        for sub in combinations(base, n):
            w: frozenset[str] = frozenset()
            for b in sub:
                w = w ^ b
            words.add(w)
    return words


def resolution_of(k: int, generators: tuple[str, ...]) -> int:
    """정의 관계의 가장 짧은 단어 길이(생성자 없음 = 전체 요인 → 정의 관계가 없어 FULL_RESOLUTION)."""
    words = defining_words(generators)
    return min((len(w) for w in words), default=FULL_RESOLUTION)


def fracfact_plan(k: int, resolution: int) -> tuple[int, tuple[str, ...], bool]:
    """(기본 요인 수 r, 생성자, 전체 요인 여부). k는 2~11, resolution은 4|5."""
    r, gens = TABLES[resolution][k]
    return r, gens, not gens


def two_level_matrix(k: int, r: int, generators: tuple[str, ...]) -> list[list[int]]:
    """Yates 순서 2^r행 × k열(−1/+1). 첫 기본 요인이 가장 빨리 바뀌고, 생성 요인 = 생성자 문자 열들의 곱."""
    letters = LETTERS[:k]
    gen_cols = []
    for g in generators:
        left, right = g.split("=")
        gen_cols.append((letters.index(left), [letters.index(c) for c in right]))
    rows: list[list[int]] = []
    for i in range(1 << r):
        base = [1 if (i >> b) & 1 else -1 for b in range(r)]
        row = base + [0] * (k - r)
        for col, srcs in gen_cols:
            p = 1
            for s in srcs:
                p *= row[s]
            row[col] = p
        rows.append(row)
    return rows


def fracfact_design(k: int, resolution: int) -> tuple[list[list[int]], dict[str, object]]:
    """(코드 행렬, {resolution, generators, runs, full})."""
    r, gens, full = fracfact_plan(k, resolution)
    return two_level_matrix(k, r, gens), {"generators": list(gens), "runs": 1 << r, "full": full}


# ---- Plackett–Burman -------------------------------------------------------------------------------


def _is_prime(n: int) -> bool:
    if n < 2:
        return False
    i = 2
    while i * i <= n:
        if n % i == 0:
            return False
        i += 1
    return True


def _paley_prime(n_runs: int) -> bool:
    q = n_runs - 1
    return _is_prime(q) and q % 4 == 3


def _is_pow2(n: int) -> bool:
    return n >= 8 and n & (n - 1) == 0


def pb_size(k: int) -> int:
    """N ≥ k+1인 가장 작은 PB 크기(집합: {q+1 : q 소수, q ≡ 3 mod 4, q+1 ≥ 8} ∪ {2^m : m ≥ 3})."""
    n = max(8, k + 1)
    while not (_paley_prime(n) and n >= 8 or _is_pow2(n)):
        n += 1
    return n


def pb_matrix(n_runs: int, k: int) -> tuple[list[list[int]], str]:
    """N행 × 앞쪽 k열(−1/+1), 구성 이름. Paley 순환(N−1 소수 ≡ 3 mod 4)을 우선하고 아니면 Sylvester."""
    if _paley_prime(n_runs):
        q = n_runs - 1
        residues = {(x * x) % q for x in range(1, q)}
        g = [1] + [1 if j in residues else -1 for j in range(1, q)]
        rows = [[g[(j - i) % q] for j in range(q)] for i in range(q)]
        rows.append([-1] * q)
        return [r[:k] for r in rows], "paley"
    h = [[1]]
    while len(h) < n_runs:
        h = [r + r for r in h] + [r + [-v for v in r] for r in h]
    return [r[1:1 + k] for r in h], "sylvester"
