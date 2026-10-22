---
name: sk_sop_qa012
title: INSP 이상 Lot 1차 판정 (SOP-QA-012)
description: |
  Lot ID 하나로 SOP-QA-012 절차대로 INSP 이상 Lot 을 1차 판정한다 — 이상 웨이퍼 선별 → 직전 공정 설비 지표 확인 → 판정(정상 / 관찰 / 엔지니어 확인 요청) → 보고 양식.
  "TE2FE35 1차 판정해줘", "이 lot Hold 해야 하는지 봐줘" 같은 요청에 사용.
tools:
- get_insp_map
- get_metric_trend
tags:
- 품질
- 공정
- SOP
- INSP
visibility: official

# ── 아래는 SOP 스킬 구조 (샘플 · 작성 규칙은 skills/README.md) ──
# 지금은 본문 절차를 LLM 이 따라 실행한다. 단계형 실행 엔진이 생기면 steps 를 그대로 실행한다.
sop:
  id: SOP-QA-012
  version: "1.0"
  owner_team: 품질팀
  document: docs/sop/SOP-QA-012_INSP_이상Lot_1차판정.md
inputs:
- name: lot_id
  label: Lot ID
  required: true
  example: TE2FE35
steps:
- id: s1
  type: data
  title: Lot INSP 결과 조회
  tool: get_insp_map
  args:
    lot_id: "{{input.lot_id}}"
- id: s2
  type: judge
  title: 이상 웨이퍼 선별
  from: [s1]
  prompt: 기준 초과(over_limit) 웨이퍼와 자동 분류 패턴(Random 이 아닌) 웨이퍼를 고르고, 그 웨이퍼들의 eq_id 를 중복 없이 모은다.
  outputs: [abnormal_slots, eq_ids]
- id: s3
  type: condition
  title: 이상 웨이퍼 없으면 종료
  if: s2.abnormal_slots 가 비어 있다
  then: s6
  verdict: 정상
- id: s4
  type: data
  title: 직전 공정 설비 막 두께 지표 조회
  tool: get_metric_trend
  for_each: s2.eq_ids
  args:
    metric: thickness
    days: 7
    equipment: "{{item}}"
- id: s5
  type: judge
  title: 판정
  from: [s1, s2, s4]
  criteria:
  - {verdict: 엔지니어 확인 요청, when: 기준 초과 웨이퍼 1장 이상 또는 관련 설비 중 OOC 3건 이상}
  - {verdict: 관찰, when: 패턴 웨이퍼만 있고 관련 설비 OOC 가 모두 3건 미만}
  - {verdict: 정상, when: 이상 웨이퍼 없음}
  outputs: [verdict, reasons]
- id: s6
  type: report
  title: 보고 양식
  template: 판정 한 줄 · 이상 웨이퍼 표 · 설비 지표 표 · 조치
---

# SOP-QA-012 INSP 이상 Lot 1차 판정

입력: Lot ID. 질문에 Lot ID 가 없으면 Lot ID 만 짧게 되묻고 멈춘다.
아래 단계를 **순서대로** 진행한다. 단계를 건너뛰거나 순서를 바꾸지 않는다. 수치는 조회 결과 그대로 쓴다.

## 단계
1. **[데이터] Lot INSP 결과 조회** — get_insp_map(lot_id) 를 호출한다.
2. **[판단] 이상 웨이퍼 선별** — over_limit 이 true 인 웨이퍼(기준 초과)와 pattern 이 Random 이 아닌 웨이퍼(패턴)를 고른다.
   이 웨이퍼들의 eq_id 를 중복 없이 모은다.
3. **[조건]** 이상 웨이퍼가 없으면 판정을 **정상** 으로 하고 6단계(보고)로 간다. 4 · 5단계는 하지 않는다.
4. **[데이터] 직전 공정 설비 지표 조회** — 2단계에서 모은 eq_id **각각**에 대해 get_metric_trend(metric=thickness, days=7, equipment=eq_id) 를 호출한다.
   설비가 여러 대면 한 번에 함께 호출한다.
5. **[판단] 판정** — 아래 기준을 위에서부터 확인해 처음 맞는 것으로 판정한다.
   | 판정 | 조건 |
   |---|---|
   | 엔지니어 확인 요청 | 기준 초과 웨이퍼 1장 이상 **또는** 관련 설비 중 OOC(ooc_count) 3건 이상 |
   | 관찰 | 패턴 웨이퍼만 있고, 관련 설비 OOC 가 모두 3건 미만 |
   | 정상 | 이상 웨이퍼 없음 |
6. **[보고]** 아래 양식 그대로 쓴다. 제목 · 순서를 바꾸지 않는다.

## 보고 양식
```
## {LOT} INSP 1차 판정 · SOP-QA-012

**판정: {정상 | 관찰 | 엔지니어 확인 요청}** — {핵심 근거 한 줄}

[WAFER_MAP:{LOT}]

### 이상 웨이퍼
| Slot | Defect | 패턴(자동 분류) | 직전 설비 | 구분 |
(구분: 기준 초과 / 패턴 / 기준 초과 · 패턴. 이상 웨이퍼가 없으면 "이상 웨이퍼 없음")

### 직전 설비 막 두께 (최근 7일)
| 설비 | 평균 두께 | OOC | 설비 의심 |
(설비 의심: OOC 3건 이상이면 '의심', 아니면 '-'. 4단계를 하지 않았으면 이 표는 생략)

### 조치
- 판정별 조치: 정상 → 다음 공정 진행 / 관찰 → 진행, 다음 Lot 에서 같은 설비 · 패턴 재발 확인 / 엔지니어 확인 요청 → Lot Hold 검토 요청, 담당 엔지니어 확인
- 확인할 항목 1~2줄 (패턴 · 설비 기준). 원인을 단정하지 않고 "확인 필요" 로 쓴다
```
