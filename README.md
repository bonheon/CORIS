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
│   │   ├── skills.py         SKILL.md 폴더 저장소
│   │   ├── memory.py         사용자 메모리 (md, 매 턴 갱신)
│   │   ├── users.py          SSO 헤더로 사용자 식별
│   │   ├── mcp_registry.py   MCP 서버별 tool 로드 · 상태 · tool 목록 미리 보기(probe)
│   │   ├── mcp_store.py      화면에서 등록한 MCP 서버 (주소 · 헤더 · 가져올 tool)
│   │   ├── store.py          대화 · 이벤터 · 등록 MCP 서버 저장 (지금은 data/hub.json)
│   │   ├── service.py        대화 저장 · 이벤터 실행/스케줄
│   │   └── mcp_data.py       화면 전용 MCP tool 호출
│   ├── routers/
│   │   ├── chat.py           POST /api/chat (SSE)
│   │   ├── hub.py            /api/hub/* — meta · MCP 서버 · 대화 · 스킬 · 이벤터 · 메모리
│   │   └── ui.py             GET /api/ui/{tool} — 카드 데이터 중계
│   ├── db/                   사용자 · 메모리 DB (SQLite, Oracle 스키마 준비)
│   └── skills/               skill = 폴더 1개 (예시: sk_notice_brief)
├── mcp_servers/
│   └── example/server.py     예시 MCP 서버 — 새 서버 만들 때 복사해서 시작
└── frontend/                 React 허브 UI
    └── src/
        ├── pages/            홈 · 채팅 · MCP 서버 · 스킬 · 이벤터 · 포탈 · 내 정보
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

## 기능 추가 방법

| 추가할 것 | 하는 일 |
|---|---|
| 회사 MCP tool | 화면 **MCP 서버** 에서 등록 · 선택 (위 절차) |
| 데이터 조회 tool (직접 개발) | MCP 서버에 tool 추가 → 화면에서 등록하거나 `catalog.yaml` 의 group 에 이름 등록 (+ `tool_labels`) |
| workflow | `backend/skills/<id>/SKILL.md` 작성 (화면 '스킬' 에서도 가능) — 필수 tool 과 절차 |
| 답변 속 카드 | MCP 에 `ui_xxx` tool → `catalog.yaml` `ui_tools` 등록 → `frontend/src/components/cards/` 에 카드 + `CARDS` 등록 → `tool_guides.yaml` 에 태그 형식 |
| 회사 MCP 연결 | `mcp_servers.yaml` 의 `company` 항목 · `.env` 의 URL/토큰 |
| 회사 LLM | `.env` 의 `LLM_BASE_URL` · `AGENT_MODEL` · `ROUTER_MODEL` · `MEMORY_MODEL` |
