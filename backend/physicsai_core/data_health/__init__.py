"""③-1 데이터 점검(data-health.md) — 학습 run 이상치 제외 추천. 순수 계산·파일 읽기(DB·외부 도구 없음).

- `stats`  일반 z(ddof=1)·견고 z(중앙값·MAD) · `knn` 파라미터 공간 kNN 튐 · `metrics` 지표 레지스트리·임계값 스냅숏·① 판정
- `attrs`  메시 include 모델 속성(bbox·부피·CoG, 서명 캐시) · `sources` run 출력(꼬리·`/RUN` Tstop·프레임 원천)·응답 읽기
- `report` 일관성·통계·kNN을 합친 run 판정·점수·`report.json`·`runs.csv`
"""
