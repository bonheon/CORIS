# Coris Skills

skill 하나 = 폴더 하나 = `<id>/SKILL.md`. 업무 workflow 단위로 등록한다.

- tool 은 MCP 서버(mcp_servers.yaml · 화면의 MCP 서버)가 제공한다. 여기서는 이름으로만 참조한다.
- 허브 화면(스킬)에서 만들거나 고쳐도 이 파일이 바뀌고, 에디터로 직접 고쳐도 된다.
- 폴더를 넣으면 skill 이 생기고, 빼면 사라진다 (서버 재시작 불필요).
- 사용 횟수 · 생성 시각은 파일이 아니라 `data/hub.json` 의 `skill_stats` 에 쌓인다.

## 1. 기본 형식

```
---
name: <폴더명과 같은 id>
title: <화면 표시명>
description: |
  언제 쓰는 skill 인지 — 검색 · 자동 선택(Router) 판단 근거
tools:            # 이 workflow 의 필수 tool (MCP tool 이름)
- get_xxx
tags: [품질, 공정]  # 자유 입력 — 대화 위 영역 탭 · 검색
visibility: official   # official(모두) | private(만든 사람 · 관리자) — 저장소에 넣는 스킬은 official
---

# 절차 본문 — 그대로 프롬프트에 들어간다
1. ...
```

## 2. SOP 스킬 작성 규칙

SOP 문서를 스킬로 옮길 때는 아래 형식을 따른다. 샘플:
**SOP 문서** [docs/sop/SOP-QA-012_INSP_이상Lot_1차판정.md](../../docs/sop/SOP-QA-012_INSP_이상Lot_1차판정.md)
→ **스킬** [sk_sop_qa012/SKILL.md](sk_sop_qa012/SKILL.md)

### SOP 문서 → 스킬 대응

| SOP 문서 | 스킬 | 비고 |
|---|---|---|
| 문서 번호 · 버전 · 담당 | frontmatter `sop: {id, version, owner_team, document}` | 제목에도 문서 번호를 넣는다 `… (SOP-QA-012)` |
| 입력 | `inputs:` | 이름 · 표시명 · 필수 여부 · 예시 |
| 절차 표의 각 행 | `steps:` 의 단계 1개 + 본문 `## 단계` 의 번호 1개 | **둘의 순서 · 번호를 똑같이** 맞춘다 |
| 확인 시스템 | 단계의 `tool` · `tools:` | tool 은 조회만. 판단을 tool 에 넣지 않는다 |
| 판정 기준 표 | 단계 `criteria` + 본문 판정 표 | 기준값(숫자)은 문서와 같은 값을 그대로 |
| 보고 양식 | 단계 `report` + 본문 `## 보고 양식` 코드 블록 | 제목 · 순서를 고정. 카드 태그 위치도 정한다 |

### 단계 종류

| type | 하는 일 | 쓰는 키 |
|---|---|---|
| `data` | tool 을 정해진 인자로 호출 (판단 없음) | `tool`, `args`, (`for_each`) |
| `judge` | 앞 단계 결과를 보고 LLM 이 판단 | `from`, `prompt` 또는 `criteria`, `outputs` |
| `condition` | 조건에 따라 다음 단계를 건너뛴다 | `if`, `then`, (`verdict`) |
| `report` | 정해진 양식으로 정리 | `template` |

인자 값 쓰는 법: 사용자 입력 `{{input.lot_id}}` · 앞 단계 결과 `s2.eq_ids` · 반복 항목 `{{item}}`

### 체크리스트
- [ ] 단계 하나에는 **tool 호출 하나 또는 판단 하나**만
- [ ] 설비 · Lot 이 여러 개인 단계는 `for_each` 로 — 본문에도 "각각 호출" 이라고 쓴다
- [ ] 판정 기준은 **위에서부터 확인해 처음 맞는 것** 으로 (겹칠 때 결과가 하나로 정해지게)
- [ ] 원인을 단정하는 문장 금지 — "확인 필요" 로
- [ ] 같은 Lot 으로 2~3번 실행해 **호출한 tool · 판정 · 표 구성이 같은지** 확인

### 지금의 실행 방식과 한계
지금은 `steps` 를 실행하는 엔진이 없어서 **본문 절차를 LLM 이 읽고 따른다.** 대부분 지키지만 보장되지는 않는다.
(샘플 테스트: 4번 중 2번 '설비마다 따로 호출' 단계를 어김 — 설비 2대를 한 번에 묶어 호출 1회, 1대를 빠뜨림 1회)
단계형 실행 엔진이 생기면 `data` · `condition` · `report` 단계는 코드가 순서대로 실행하고 LLM 은 `judge` 단계에서만 쓰인다.
`steps` 를 미리 써 두는 이유가 이것이다 — 같은 파일을 그대로 실행하게 된다.
