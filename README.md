# Coris

사내 업무 Super Agent 허브. **MCP tool → workflow skill** 구조로 기능을 늘린다.

- tool = 단순 데이터 조회. MCP 서버 안에 둔다.
- 판단 · 절차 = skill (`backend/skills/<id>/SKILL.md`). 업무 workflow 하나당 skill 하나.
- agent 는 프롬프트(업무 방식)가 다를 때만 늘린다.

## 구조

```
CORIS/
├── backend/                  FastAPI + LangGraph 허브
│   ├── main.py               진입점 — MCP tool 주기 갱신, 이벤터 스케줄러(옵션)
│   ├── agent.py              LangGraph 실행 — tool 조합별 그래프 캐시, 이전 턴 tool 결과(trace) 재주입
│   ├── mcp_servers.yaml      MCP 서버 접속 정보 (tool 은 전부 여기서 온다)
│   ├── hub/
│   │   ├── llm.py            LLM 생성 — 회사 LLM 게이트웨이로 바꿀 때 여기 + .env
│   │   ├── catalog.py/.yaml  group · agent · ui_tools · tool 표시명 · 포탈
│   │   ├── tool_guides.yaml  tool 별 프롬프트 안내 (카드 태그 형식 등)
│   │   ├── routing.py        agent · skill 자동 선택 + 최종 tool 계산
│   │   ├── jev.py            Jev 방식 agent 선택 — 기호 1토큰 + logprobs 확률 · 신뢰도, 낮으면 Coris
│   │   ├── runs.py           진행 중인 답변 — 화면 연결과 분리 (답변 중 · 다시 연결 · 중지)
│   │   ├── steps.py          단계 실행 엔진 — SKILL.md inputs · steps 를 순서대로 (조회 · 반복 · 표는 코드, 판단만 LLM)
│   │   ├── skills.py         SKILL.md 폴더 저장소
│   │   ├── memory.py         사용자 메모리 (md, 매 턴 갱신)
│   │   ├── users.py          SSO 헤더로 사용자 식별
│   │   ├── mcp_registry.py   MCP 서버별 tool 로드 · 상태 · tool 목록 미리 보기(probe)
│   │   ├── mcp_store.py      화면에서 등록한 MCP 서버 (주소 · 헤더 · 가져올 tool)
│   │   ├── store.py          대화 · 이벤터 · 작업 큐 · 등록 MCP 서버 · tool 그룹 저장 (지금은 data/hub.json)
│   │   ├── service.py        대화 저장 · 이벤터 스케줄 · 작업 큐(task table, 전역 1개 · 순차 1건씩)
│   │   ├── tool_groups.py    그룹 메뉴에서 만든 tool 그룹 (서버 상관없이 tool 묶음 + 영역 태그)
│   │   ├── offload.py        큰 tool 결과 자동 보관 — 저장소에 넣고 LLM 에는 요약 + data_ref
│   │   ├── tabular.py        tool 결과(JSON · 마크다운 표) → 표 변환 · 타입 추정 · 열 통계
│   │   ├── storage.py        저장소 — local 폴더 | 사내 S3 (STORAGE=)
│   │   └── mcp_data.py       화면 전용 MCP tool 호출
│   ├── routers/
│   │   ├── chat.py           POST /api/chat (SSE)
│   │   ├── hub.py            /api/hub/* — meta · MCP 서버 · tool 그룹 · 대화 · 스킬 · 이벤터 · 작업 큐 · 메모리
│   │   └── ui.py             GET /api/ui/{tool} — 카드 데이터 중계
│   ├── db/                   사용자 · 메모리 DB (SQLite, Oracle 스키마 준비)
│   └── skills/               skill = 폴더 1개 (예시: sk_notice_brief)
├── mcp_servers/
│   ├── example/server.py     예시 MCP 서버 — 새 서버 만들 때 복사해서 시작
│   ├── fab_sample/           FAB 샘플 (:8130) — Lot 진행 이력 · 장비 일 효율 각 약 1,000행, 마크다운 표 결과
│   │                         (gen_data.py 로 CSV 생성 · server.py 로 조회)
│   └── code_interpreter/     Python 실행 (:8120) — 대화별 Jupyter 커널
└── frontend/                 React 허브 UI
    └── src/
        ├── pages/            홈 · 채팅 · MCP 서버 · tool 그룹 · 스킬 · 스케줄링 · 작업 목록 · 포탈 · 내 정보
        ├── shell/            Rail · 대화 목록 · Composer · ToolPicker
        └── components/
            ├── MessageBubble.tsx, RunTrace.tsx
            └── cards/        카드 태그 레지스트리 (예시: NoticeListCard)
```

## 실행

```bash
# 1) backend venv
cd backend && python -m venv venv && source venv/bin/activate && pip install -r requirements.txt
cp .env.example .env   # LLM_API_KEY 등 채우기

# 2) 예시 MCP 서버 (:8100)
cd ../mcp_servers/example && python server.py

# 2-1) FAB 샘플 MCP 서버 (:8130) — 데이터가 없으면 gen_data.py 먼저
cd ../fab_sample && python gen_data.py && python server.py

# 3) backend (:8000)
cd ../../backend && uvicorn main:app --reload

# 4) frontend (:3000, /api 는 8000 으로 프록시)
cd ../frontend && npm install && npm start
```

## 회사 MCP 서버 붙이기 (화면)

1. 왼쪽 메뉴 **MCP 서버** → **서버 등록**
2. ID · 이름 · URL · 인증 헤더 입력 → **tool 목록 불러오기** (서버의 `list_tools` 결과를 미리 봄, 저장 전)
3. Coris 에서 쓸 tool 만 체크 (필요하면 화면 표시명 입력) → **저장** — 바로 반영, 재시작 불필요
4. **선택한 tool 로 스킬 만들기** → 스킬 화면에서 절차 작성 후 저장

- 서버 하나 = tool 그룹 하나 (`mcp_<id>`). 대화의 tool 선택 · 스킬 편집 화면에 서버 이름으로 묶여 나온다.
- **기본으로 켜기**: 켜면 질문마다 LLM 이 이 tool 들을 본다. tool 이 많은 서버는 끄고 스킬로만 쓰는 게 선택 정확도에 좋다.
- 헤더 값은 저장 후 가려진다. 토큰을 저장하지 않으려면 `${ENV_VAR}` 로 쓰고 `.env` 에 둔다.
- 이름이 `ui_` 로 시작하는 등 `catalog.yaml` `ui_tools` 에 있는 tool 은 화면 전용이라 고를 수 없다 (카드용으로는 자동으로 받아 둔다).
- 배포 설정으로 고정할 서버는 지금처럼 `mcp_servers.yaml` 에 적는다 (화면에서는 조회만).

## 스케줄링 · 작업 목록

화면 메뉴: **스케줄링**(일정 등록 · 실행) / **작업 목록**(작업 큐 · 작업 기록, task table).
스케줄링(코드상 events)은 agent 를 직접 부르지 않고 **작업 큐(task table)** 에 task 를 넣는다 — `hub/service.py`.

- 정해진 시각(`HUB_SCHEDULER=1`) · 화면의 "실행" · 실패 task 의 "다시 실행" → task `queued`
- worker 하나가 넣은 순서대로 **한 번에 한 건** 처리: `queued → running → done | error` (대기 중은 `canceled` 로 취소 가능)
- 같은 이벤트가 아직 대기 · 실행 중이면 예약 회차는 건너뛴다. 서버 재시작 시 `running` 으로 남은 task 는 `error`
- API: `POST /api/hub/events/{id}/run` (task 반환) · `GET /api/hub/tasks` · `POST /api/hub/tasks/{id}/cancel|retry`

## skill 단계 실행 (실행 방식 ③)

SKILL.md 에 `steps` 가 있으면 LLM 이 tool 순서를 정하지 않고 엔진(`hub/steps.py`)이 정해진 순서로 실행한다.
화면 **스킬 → 단계** 에서 만들고 고친다 (저장 전에 단계 정의를 검사). 단계가 없으면 지금처럼 프롬프트로 동작.

| 단계 | 하는 일 | 실행 |
|---|---|---|
| 조회 `data` | tool 호출, `for_each` 면 항목마다 동시에 | 코드 |
| 계산 `compute` | 표 만들기(`table`) · 중복 제거(`unique`) · 행 거르기(`filter`) | 코드 |
| 조건 `condition` | `empty(s1.rows)` 등은 코드, 문장 조건은 LLM 예/아니오 → 참이면 건너뛰기 | 코드 / LLM |
| 판단 `judge` | 앞 단계 요약으로 판단 — 기준이 있으면 기준마다 참/거짓을 먼저 적고 처음 참인 판정 | LLM |
| 보고 `report` | `{{…}}` 가 있으면 코드가 채움(항상 같은 양식), 없으면 본문 '## 보고 양식' 대로 LLM | 코드 / LLM |

참조: `{{input.lot_id}}` · `{{item.eqp_id}}` · `{{s1.count}}` · `{{s3[i].bm_hr|first}}` · `{{table:s6}}` · `{{s7.text}}` · `{{verdict}}`
시험 (2026-11-19, Hold Lot 보고 · 3회): 단계형 5.0~6.1초 / 프롬프트형 8.7~9.4초, 표는 둘 다 3회 동일. SOP-QA-012 는 설비별 조회를 빠짐없이 실행.

## agent 선택 (Jev 방식)

agent 3개 — `catalog.yaml` 의 `route_criteria`(포함 · 제외 기준)로 고른다.

| agent | 가는 질문 |
|---|---|
| Coris (기본) | MCP tool 데이터 조회 · 집계 · 차트, 공지, 일반 · 복합 질문 — 신뢰도가 낮을 때도 여기로 |
| Ceeria | C/C 기준 · SOP · 용어 · 절차 지식 질문 (`search_knowledge`, 지금은 Mock) |
| Trouble Lot | Hold Lot 처리 · 원인 · 해제 전 확인 |

`hub/jev.py`: 사내 LLM 에 선택지 기호 하나만 답하게 하고(max_tokens=1) logprobs 로 선택지별 확률을 낸다.
1위 확률 ≥ `JEV_MIN_CONF`(0.6) 이면 확정, 아니면 Coris. skill 은 기존 Router 가 동시에 고른다.
`ROUTER_AGENT_MODE=llm` 이면 예전처럼 Router 가 agent 도 고른다. 사내 LLM 게이트웨이가 logprobs 를 지원해야 한다.

## 큰 tool 결과 처리 (offload)

tool 결과 표준(JSON 공통 형식) — 조건에 맞는 **전체 행**을 준다 (요약 · 일부만 주지 않는다):
`{"summary", "columns": [{"name", "label", "type", "unit"}], "rows": [[...]], "meta": {"source", "query", "row_count", "truncated"}}`
작은 결과도 공통 형식이면 Coris 가 '요약 + 마크다운 표' 로 바꿔 LLM 에 넘긴다.

tool 결과가 `OFFLOAD_CHARS`(기본 6,000자)를 넘고 표로 읽히면(JSON · 마크다운 표), `OFFLOAD_MIN_ROWS`(기본 20행) 이상인 표를
저장소에 보관하고 LLM 에는 **행 수 · 열 타입 · 열별 통계 · 앞 5행 · data_ref** 만 보낸다. LLM 은 계산이 필요하면
`run_python` 에서 `df = load_ref("dr_...")` 로 원본을 불러 pandas 로 계산한다. 회사 MCP 서버는 고칠 필요 없다 (Coris 가 감싼다).

- 저장: `tool-results/<ref>.json.gz` — `STORAGE=local` 이면 `backend/data/blobs/`, `STORAGE=s3` 면 사내 S3 (`S3_*`, boto3 필요)
- 보관 기간: local 은 `STORAGE_TTL_DAYS`(기본 7일) 지나면 자동 삭제, S3 는 버킷 lifecycle 규칙(prefix `tool-results/`)
- 접근: `GET /api/hub/data/{ref}` — 커널이 보내는 `X-Coris-Session` 이 data_ref 를 만든 대화와 같아야 한다
- 시험 (fab_sample, 2026-11-19): "장비별 평균 가동률 순위" 1,008행 — 전: 19.8초 · 수치 틀림 / 후: 11.3초 · 정확

## tool 그룹 메뉴

왼쪽 메뉴 **tool 그룹** — MCP 서버와 상관없이 tool 을 칩(태그)으로 골라 그룹을 만들고, 그룹마다 영역 태그를 단다.
저장하면 바로 반영 (대화 위 영역 탭 · ⚙ tool 선택 · 스킬 편집). `include_imported` agent 의 허용 범위에 들어가고,
'기본으로 켜기' 면 기본 그룹에도 들어간다. API: `/api/hub/tool-groups` (GET · POST · PUT · DELETE).

## 기능 추가 방법

| 추가할 것 | 하는 일 |
|---|---|
| 회사 MCP tool | 화면 **MCP 서버** 에서 등록 · 선택 (위 절차) |
| 데이터 조회 tool (직접 개발) | MCP 서버에 tool 추가 → 화면에서 등록하거나 `catalog.yaml` 의 group 에 이름 등록 (+ `tool_labels`) |
| workflow | `backend/skills/<id>/SKILL.md` 작성 (화면 '스킬' 에서도 가능) — 필수 tool 과 절차 |
| 답변 속 카드 | MCP 에 `ui_xxx` tool → `catalog.yaml` `ui_tools` 등록 → `frontend/src/components/cards/` 에 카드 + `CARDS` 등록 → `tool_guides.yaml` 에 태그 형식 |
| 회사 MCP 연결 | `mcp_servers.yaml` 의 `company` 항목 · `.env` 의 URL/토큰 |
| 회사 LLM | `.env` 의 `LLM_BASE_URL` · `AGENT_MODEL` · `ROUTER_MODEL` · `MEMORY_MODEL` |
