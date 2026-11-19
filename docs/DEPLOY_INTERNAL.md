# Coris 사내 배포 · 시험 가이드

> 대상: 사내 PC/서버에서 Coris 를 처음 띄우고 시험하는 사람과 코딩 도구(LLM).
> 기준: 2026-11-20 로컬 개발본. 코드 수정 없이 `.env` 와 설치만으로 옮기는 것을 목표로 한다.

## 0. 핵심 요약

- **그대로 실행만 하면 안 된다.** 로컬본은 외부 OpenAI · 다른 폴더(Agent)의 venv 와 `.env` · Mock 데이터에 기대고 있다.
- 바꿀 것은 대부분 `backend/.env` 다. 코드 수정은 필요 없다.
- 사내 LLM 게이트웨이(OpenAI 호환)가 **function calling** 을 지원해야 한다 (필수). **logprobs** · **structured output** 은 없으면 일부 기능이 약해진다 (2절).
- 옮기지 말 것: `backend/data/`, `mcp_servers/code_interpreter/workspace/`, `node_modules/`, `venv/` · `.venv/`, `__pycache__/`.

## 1. 반드시 바꿀 것

| 항목 | 로컬본 | 사내 | 설정 위치 |
|---|---|---|---|
| LLM | OpenAI 외부 API (gpt-4o · gpt-4o-mini) | 사내 LLM 게이트웨이 | `LLM_BASE_URL`, `LLM_API_KEY`, `AGENT_MODEL`, `ROUTER_MODEL`, `MEMORY_MODEL`, `SUGGEST_MODEL`, (`JEV_MODEL`, `STEP_JUDGE_MODEL` — 비우면 위 값) |
| 이미지 해석(VLM) | gpt-4o | 사내 VLM 또는 끄기 | `VISION_BASE_URL`, `VISION_MODEL`, `VISION_API_KEY` / 없으면 `VISION_MODE=off` |
| `.env` | `Agent/backend/.env` 를 빌려 씀 | `backend/.env.example` → `backend/.env` 복사 후 채움 | `backend/.env` |
| Python 환경 | `Agent/backend/venv` 를 빌려 씀 | 백엔드 · MCP 서버용 venv 새로 | `backend/requirements.txt` |
| code interpreter 환경 | 전용 `.venv` | 전용 venv 새로 | `mcp_servers/code_interpreter/requirements.txt` |
| 관리자 | 기본 사번 2057197 | 본인 사번 | `ADMIN_USERS` |
| 사용자 식별 | 헤더 없으면 "개발 사용자"(dev.user) | 사내 SSO 헤더 | `USER_ID_HEADER`, `USER_NAME_HEADER`, `USER_DEPT_HEADER` |
| 폴더 이름 | `CORIS ` (끝에 공백) | `CORIS` 로 바꿔서 둘 것 | — |

## 2. 사내 LLM 게이트웨이 확인 사항

| 기능 | 게이트웨이에 필요한 것 | 없을 때 동작 | 확인 방법 |
|---|---|---|---|
| tool 호출 (모든 조회) | function calling | **동작 안 함 (필수)** | 시험 2 |
| 답변 스트리밍 | stream | 답변이 한 번에 나옴 | 시험 1 |
| Router · skill 자동 선택 · 입력값 추출 | structured output / JSON 응답 | Router 실패 → 기본 agent(Coris) 로 처리, skill 자동 선택 안 됨 | 시험 4 의 처리 과정 |
| Jev agent 선택 | `logprobs`, `top_logprobs` | 답한 기호만 사용 (확률 · 신뢰도 없음, 동작은 함) | 시험 4 처리 과정에 "Jev: Ceeria 0.97 · …" 처럼 확률이 보이면 지원 |

- 확률이 안 나오고 분기가 불안정하면 `ROUTER_AGENT_MODE=llm` (예전 Router 가 agent 도 고름).
- 사내 모델은 성능이 다르다. `JEV_MIN_CONF`(기본 0.6), 단계형 skill 의 판단 결과는 다시 확인한다. 로컬 gpt-4o-mini 는 신뢰도가 거의 항상 1.00 이라 기준이 작동하지 않았다.

## 3. 데이터 · tool

- **예시 서버(`mcp_servers/example`, :8100)** · **FAB 샘플 서버(`mcp_servers/fab_sample`, :8130)** 는 Mock 데이터. 사내에서도 그대로 돌아가며 기능 시험용으로 쓴다.
- **사내 실제 데이터**: 화면 **MCP 서버 → 서버 등록** 으로 사내 MCP 서버를 붙인다 (주소 · 인증 헤더 → tool 목록 불러오기 → 쓸 tool 선택 → 저장). 재시작 불필요.
  - tool 결과는 JSON 공통 형식 권장: `{"summary", "columns": [{"name","label","type","unit"}], "rows": [[...]], "meta": {"source","query","row_count","truncated"}}`. 마크다운 표도 읽지만 타입을 추정한다.
- **시범 skill `sk_hold_report`(단계형)** 은 FAB 샘플 tool 이름(`get_lot_history`, `get_eqp_efficiency`, `search_knowledge`)을 쓴다. 사내 tool 로 시험하려면 화면 **스킬 → 복제해서 내 스킬로 → 단계** 에서 tool · 인자를 바꾼다.
- **Ceeria 지식 검색(`search_knowledge`)** 은 Mock (`docs/` 의 md + Mock 문서 3개를 키워드로 검색). 사내 Ceeria 검색 tool 이 있으면 `backend/hub/catalog.yaml` 의 `knowledge` 그룹 tool 을 그것으로 바꾼다.
- **저장소(큰 tool 결과 보관)**: 처음엔 `STORAGE=local`(`backend/data/blobs/`). 사내 S3 시험 시 `STORAGE=s3` + `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_PREFIX`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` + `pip install boto3`. 버킷에 `tool-results/` prefix lifecycle(예: 7일 삭제) 규칙을 건다.

## 4. 설치 · 실행 (사내 PC 기준, 터미널 여러 개)

```bash
# 0) 옮겨 온 폴더에서 (데이터 · venv · node_modules 는 가져오지 않는다)
cd CORIS

# 1) 백엔드 + 예시 · FAB MCP 서버용 venv
cd backend
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt                      # 사내 pip 미러가 있으면 -i <미러주소>
cp .env.example .env                                 # 1절 · 2절 값 채우기

# 2) MCP 서버 (위 venv 로)
cd ../mcp_servers/example && python server.py                         # :8100
cd ../fab_sample && python gen_data.py && python server.py           # :8130 (gen_data 는 처음 한 번)

# 3) code interpreter (전용 venv)
cd ../code_interpreter
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python server.py                                           # :8120

# 4) 백엔드 (MCP 서버가 뜬 뒤 — 늦게 떠도 60초마다 다시 붙는다)
cd ../../backend && uvicorn main:app --port 8000                     # 개발 중이면 --reload

# 5) 프런트 (:3000, /api 는 8000 으로 프록시)
cd ../frontend && npm install && npm start
```

- 포트를 바꾸면 `.env` 의 `EXAMPLE_MCP_URL`, `CODE_MCP_URL`, `FAB_MCP_URL` 도 같이 바꾼다.
- 스케줄링 예약 실행은 `HUB_SCHEDULER=1` 일 때만 (LLM 비용 때문에 기본 꺼짐). "실행" 버튼은 항상 동작.

## 5. 시험 순서

| # | 할 일 | 기대 결과 | 확인하는 것 |
|---|---|---|---|
| 1 | "안녕" | 답변이 스트리밍으로 나옴 | LLM 연결 · 스트리밍 |
| 2 | "ETCH-03 11월 4일 가동률 알려줘" | `get_eqp_efficiency(eqp_id=ETCH-03, date_from=2026-11-04, …)` 호출, 가동률 22.5% | function calling · 인자 추출 |
| 3 | "전체 기간 동안 장비별 평균 가동률 하위 3개는?" | 처리 과정에 `run_python` + `load_ref("dr_…")`, 답 ETCH-03 75.5% · PHOTO-02 76.4% · DIFF-02 78.6% | 큰 결과 보관 · 저장소 · code interpreter |
| 4 | "Hold 해제 절차가 어떻게 돼?" | agent = Ceeria, 처리 과정 분기 이유에 "Jev: Ceeria …" 확률 | Jev agent 선택 · logprobs |
| 5 | 스킬 "Hold Lot 현황 보고 (단계형)" 켜고 "Hold Lot 보고서" | 단계 11개(조회 · 조건 · 반복 · 표 · 판단 · 보고) 순서대로, 표에 L5N0057.1 · D160061.1 | 단계 실행 엔진 · structured/JSON 응답 |
| 6 | 질문을 보내고 바로 다른 대화로 이동 | 목록에 "답변 중" → "답변 완료" | 백그라운드 답변 |

FAB 샘플 데이터 기준 시각은 2026-11-19 09:00, 장비 효율 기간은 2026-10-08 ~ 2026-11-18 이다.

## 6. 주의 · 알려진 제한

- **code interpreter 는 격리되지 않은 로컬 프로세스**(백엔드와 같은 권한). 시험용으로만 쓰고, 여러 사람에게 열기 전에 컨테이너 격리 필요 (TODO 3).
- **tool 호출 시간 제한 없음** — MCP 서버 하나가 멈추면 답변이 멈춘다 (TODO 1).
- **대화 목록이 사용자별로 나뉘지 않는다** — 전체 삭제는 모든 사용자의 대화(즐겨찾기 제외)를 지운다.
- **진행 중인 답변은 서버 메모리에만** 있다 — 백엔드 재시작 시 그때 답변 중이던 것은 사라진다 (`--reload` 개발 모드는 코드 수정마다 재시작).
- **저장소 전부 파일** — 대화 · 스케줄 · 작업 큐 · 등록 MCP 서버 · tool 그룹은 `backend/data/hub.json`, 사용자 · 메모리는 SQLite. 운영 전 DB 이전 필요 (TODO 1).
- 차트 카드의 "저장" 으로 받은 HTML 파일만 외부 CDN(plotly) 을 참조한다. 화면 안 차트는 내장 plotly(`frontend/public/vendor`)로 사내망에서도 보인다.
- 공식 skill 은 `ADMIN_USERS` 만 편집. 그 외 사용자는 "복제해서 내 스킬로" 후 편집.

## 7. 구조 빠른 참조 (코딩 도구용)

| 하고 싶은 것 | 파일 |
|---|---|
| LLM · 모델 연결 | `backend/hub/llm.py`, `.env` |
| agent 정의 · tool 그룹 · Jev 기준(route_criteria) | `backend/hub/catalog.yaml` |
| agent 선택(Jev) | `backend/hub/jev.py`, `backend/hub/routing.py` |
| 큰 tool 결과 보관 · 요약 | `backend/hub/offload.py`, `backend/hub/tabular.py`, `backend/hub/storage.py` |
| 단계형 skill 실행 · 검사 | `backend/hub/steps.py`, skill 파일 `backend/skills/<id>/SKILL.md`, 규칙 `backend/skills/README.md` |
| 답변 백그라운드 실행 · 다시 연결 · 중지 | `backend/hub/runs.py`, `backend/routers/chat.py` |
| 스케줄링 · 작업 큐 | `backend/hub/service.py` |
| tool 사용 안내(프롬프트) | `backend/hub/tool_guides.yaml` |
| code interpreter · 도우미 함수(load_ref · trend_chart · 차트 테마) | `mcp_servers/code_interpreter/server.py`, `kernel_init.py` |
| 화면 | `frontend/src/pages/*`, `frontend/src/components/*` |

설계 배경 문서: `docs/skill-steps.html` (단계형 skill 알고리즘), README 의 "큰 tool 결과 처리" · "skill 단계 실행" · "agent 선택 (Jev 방식)" 절.
