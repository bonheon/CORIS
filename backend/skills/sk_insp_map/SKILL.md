---
name: sk_insp_map
title: INSP Wafer Map 정리
description: |
  Lot ID 하나로 INSP(검사) 결과를 정해진 양식으로 정리한다 — 웨이퍼 맵 카드, 웨이퍼별 표, 이상 웨이퍼와 근거, 다음 확인 항목.
  "TE2FE35 INSP 정리해줘", "이 lot 웨이퍼 맵 정리" 같은 요청에 사용.
tools:
- get_insp_map
tags:
- 품질
- 공정
- INSP
visibility: official
---

입력: Lot ID. 질문에 Lot ID 가 없으면 Lot ID 만 짧게 되묻고 멈춘다.

1. get_insp_map 으로 Lot 의 검사 결과를 조회한다.
2. 아래 양식 그대로, 순서와 제목을 바꾸지 않고 작성한다. 수치는 조회 결과 그대로 쓴다.

```
## {LOT} INSP 정리 · {step}

**요약** — 웨이퍼 {n}장 · 총 defect {total} · 웨이퍼당 평균 {mean} (기준 {limit}) · 기준 초과 {k}장 · 패턴 웨이퍼 {m}장

{결과의 chart 태그 — [WAFER_MAP:LOT]}

### 웨이퍼별 결과
| Slot | Defect | 주요 유형 | 패턴(자동 분류) | 판정 |
(행 구성 — 빠뜨리지 않는다:
   ① 판정이 '정상' 이 아닌 웨이퍼 전부 (기준 초과 → 패턴 순)
   ② 정상 웨이퍼 중 summary.slots_by_defect_desc 에서 앞쪽 3장 — 비교 기준선
 판정은 '기준 초과' / '패턴' / '정상' — 기준 초과이면서 패턴이면 '기준 초과 · 패턴')

### 이상 웨이퍼
- Slot {n}: {판정 근거 한 줄 — 수치 · 패턴 · 주요 유형}
(판정이 '정상' 이 아닌 웨이퍼 — 기준 초과와 패턴 웨이퍼 — 를 모두 쓴다. 없으면 "이상 웨이퍼 없음")

### 유형별 분포
PARTICLE {n} · SCRATCH {n} · RESIDUE {n} · PIT {n} · BRIDGE {n}

### 다음 확인
- 패턴별 확인 항목을 1~3줄로 제안한다
  (Edge → 엣지 클램프 · 베벨 세정, Center → 척 · 노즐 · 중심부 공정 조건, Scratch → 이송 · 핸들링 · CMP 패드, Cluster → 해당 위치 장비 이물 · 이전 step 확인)
- 원인을 단정하지 않는다 — "확인 필요" 로 쓴다
```

3. 사용자가 특정 Slot 을 다시 물으면 같은 데이터로 그 Slot 만 자세히 답한다 (다시 조회하지 않는다).
