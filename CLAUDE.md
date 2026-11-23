# Coris

사내 업무 Super Agent 허브 — FastAPI + LangGraph 백엔드(`backend/`), React 화면(`frontend/`), MCP 서버(`mcp_servers/`).
구조 · 기능 설명은 `README.md`, 남은 작업은 `TODO.md`.

## 사내 배포 · 시험

사내 환경으로 옮기거나 실행 · 시험할 때는 먼저 `docs/DEPLOY_INTERNAL.md` 를 읽는다.
요점: 그대로 실행하면 안 된다 — `backend/.env` 를 새로 만들고(LLM 게이트웨이 · 모델 · ADMIN_USERS),
venv 를 새로 설치하며, `backend/data/` · `mcp_servers/code_interpreter/workspace/` 는 옮기지 않는다.

응답 속도 · ReAct 반복 관련 작업은 `docs/AGENT_SPEED.md`(검토 · 적용 · 남은 작업), 측정은 `docs/TIMING.md`.
대화 기록이 사라짐 · 대화 불러오기가 느림 · 답변 중 대화 열기 문제는 `docs/CONVERSATION_STABILITY.md`.

## 원칙

- tool = 단순 데이터 조회 (MCP 서버). 판단 · 절차 · 보고 양식 = skill (`backend/skills/<id>/SKILL.md`). agent 는 프롬프트가 다를 때만 늘린다.
- 정해진 보고 · 반복 · 수치 계산은 LLM 프롬프트보다 코드로 고정한다 — 단계형 skill(`hub/steps.py`) · 도우미 함수(`trend_chart` 등).
- 큰 tool 결과는 LLM 에 넣지 않는다 — 저장소에 보관하고 요약 + `data_ref` 만 (`hub/offload.py`), 계산은 `run_python` 의 `load_ref`.
- 설정은 `.env` 로 바꾸게 만들고, 새 설정을 추가하면 `backend/.env.example` 에도 적는다.

## 실행 (로컬)

`docs/DEPLOY_INTERNAL.md` 4절 순서. 포트: 화면 3000 · 백엔드 8000 · 예시 MCP 8100 · code interpreter 8120 · FAB 샘플 8130.
