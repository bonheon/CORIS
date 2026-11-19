---
name: sk_hold_report_prompt
title: Hold Lot 현황 보고 (프롬프트형)
description: |
  sk_hold_report 와 같은 보고를 프롬프트만으로 실행하는 비교용 skill (실행 방식 ①). 자동 선택 대상이 아니다 — 비교 시험에서 직접 지정.
tools:
- get_lot_history
- get_eqp_efficiency
- search_knowledge
tags:
- 비교시험
visibility: official
---

# Hold Lot 현황 보고 (프롬프트형)

아래 절차를 순서대로 진행한다. 수치는 조회 결과 그대로 쓴다.

1. get_lot_history(status=HOLD) 로 현재 HOLD Lot 을 조회한다. 없으면 'Hold Lot 없음' 으로 보고하고 끝낸다.
2. HOLD Lot **각각**에 대해 그 Lot 의 설비(eqp_id)와 Hold 발생 날짜(track_in 날짜)로 get_eqp_efficiency 를 호출한다.
3. HOLD Lot **각각**에 대해 같은 설비 · 같은 날짜로 get_lot_history 를 호출해 같은 날 진행한 Lot 수를 센다.
4. HOLD Lot **각각**의 Hold 사유로 search_knowledge("<사유> Hold 해제 기준", top_k=2) 를 호출한다.
5. 아래 양식으로 보고한다.

## 보고 양식
```
## Hold Lot 현황 · {N}건
| Lot | 제품 | 공정 | 설비 | Hold 사유 | Hold 시각 | 설비 당일 BM(h) | 설비 당일 가동률(%) | 같은 설비 당일 Lot 수 |

### 해제 판단
- Lot 마다 '해제 검토 가능 / 보류 / 엔지니어 확인 필요' 중 하나 + 근거 한 줄 + 해제 전 확인 사항(최대 2줄), 출처(문서 id · 섹션)
```
