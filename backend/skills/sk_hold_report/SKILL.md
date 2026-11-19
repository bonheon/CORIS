---
name: sk_hold_report
title: Hold Lot 현황 보고 (단계형)
description: |
  현재 HOLD 상태인 Lot 전체를 정해진 양식으로 보고한다 — Lot 별 Hold 사유 · 설비 당일 BM · 가동률 · 같은 설비 당일 Lot 수 · 처리 기준 · 해제 판단.
  "Hold Lot 보고서 만들어줘", "Hold 현황 보고해줘" 같은 요청에 사용. (단계 실행 엔진 시범)
tools:
- get_lot_history
- get_eqp_efficiency
- search_knowledge
tags:
- 품질
- 공정
- Hold
visibility: official
steps:
- id: s1
  type: data
  title: 현재 HOLD Lot 조회
  tool: get_lot_history
  args:
    status: HOLD
- id: s2
  type: condition
  title: HOLD Lot 이 없으면 바로 보고
  if: empty(s1.rows)
  then: end
  verdict: Hold Lot 없음
- id: s3
  type: data
  title: Hold 설비의 당일 효율
  tool: get_eqp_efficiency
  for_each: s1.rows
  args:
    eqp_id: "{{item.eqp_id}}"
    date_from: "{{item.track_in|date}}"
    date_to: "{{item.track_in|date}}"
- id: s4
  type: data
  title: 같은 설비 · 같은 날 진행 Lot
  tool: get_lot_history
  for_each: s1.rows
  args:
    eqp_id: "{{item.eqp_id}}"
    date_from: "{{item.track_in|date}}"
    date_to: "{{item.track_in|date}}"
- id: s5
  type: data
  title: Hold 사유별 처리 기준 문서
  tool: search_knowledge
  for_each: s1.rows
  args:
    query: "{{item.hold_reason}} Hold 해제 기준"
    top_k: 2
- id: s6
  type: compute
  title: Lot 별 요약 표
  op: table
  for_each: s1.rows
  columns:
    Lot: "{{item.lot_id}}"
    제품: "{{item.product}}"
    공정: "{{item.step_name}}"
    설비: "{{item.eqp_id}}"
    Hold 사유: "{{item.hold_reason}}"
    Hold 시각: "{{item.track_out}}"
    설비 당일 BM(h): "{{s3[i].bm_hr|first}}"
    설비 당일 가동률(%): "{{s3[i].utilization_pct|first}}"
    같은 설비 당일 Lot 수: "{{s4[i].lot_id|unique|count}}"
- id: s7
  type: judge
  title: Lot 별 해제 판단
  from: [s6, s5]
  prompt: Lot 마다 '해제 검토 가능 / 보류 / 엔지니어 확인 필요' 중 하나와 근거 한 줄, 해제 전 확인 사항(최대 2줄)을 쓴다. 처리 기준은 문서 id · 섹션을 출처로 붙인다. 원인을 단정하지 않는다.
- id: s8
  type: report
  title: 보고서
  template: |
    ## Hold Lot 현황 · {{s1.count}}건
    {{s1.summary}}

    {{table:s6}}

    ### 해제 판단
    {{s7.text}}
---

# Hold Lot 현황 보고 (단계형)

단계 실행 엔진이 위 steps 를 순서대로 실행한다 — 조회 · 반복 · 표는 코드, 해제 판단만 LLM.
