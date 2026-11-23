# 응답 시간 측정 — 어디서 느린지 나눠 보기

"답변이 느리다 · 화면이 실시간이 아니다"의 원인은 크게 세 군데다. 측정은 이 셋을 나눠서 본다.

```
[서버] LLM · tool · DB · 서버 멈춤   →   [전송] 프록시 · gzip · 로드밸런서   →   [화면] 받기 · 그리기
   hub/timing.py (로그)               scripts/measure_stream.py (도착 시각)     frontend/src/timingProbe.ts (콘솔)
```

같은 질문을 세 곳에서 재고 `conversation_id`로 짝지으면 어느 구간이 시간을 쓰는지 바로 보인다.

---

## 1. 구성

| 파일 | 하는 일 | 켜는 법 |
|---|---|---|
| `backend/hub/timing.py` | 질문마다 구간별 시간 기록 — LLM 호출(모델 · 시간 · 첫 토큰까지 · 입력 길이) · tool · DB · Router · 추천 질문 · 첫 글자 · **서버 멈춤(event loop)** | 기본 켜짐 (`TIMING=0` 이면 끔). `TIMING_LOG=data/timing.jsonl` 이면 JSON 으로도 쌓임 |
| `backend/scripts/measure_stream.py` | 브라우저 없이 `/api/chat` 에 질문을 보내 이벤트가 **도착한** 시각을 잰다. 한꺼번에 몰려 오면 경고 | 명령으로 실행 |
| `frontend/src/timingProbe.ts` | 브라우저가 받은 시각 · 네트워크 묶음 · **화면이 멈춘 시간(longtask)** | 콘솔에서 `localStorage.setItem("coris.timing","1")` 후 새로고침 |

로컬 참조본에서 연결된 위치 (회사판도 같은 자리에 넣는다)

| 위치 | 넣은 것 |
|---|---|
| `backend/main.py` lifespan | `timing.start_loop_monitor()` — 서버 멈춤 감시 |
| `backend/main.py` 미들웨어 | `app.add_middleware(timing.RequestStartMiddleware)` — 요청 도착 시각 (인증 · 사용자 조회 시간 포함) |
| `backend/routers/chat.py` `chat()` | `Timing` 생성, DB 읽기 구간(`db.load_conversation` · `db.skills` · `db.user_memory`) |
| `backend/routers/chat.py` `generate()` | `timing.activate(t)`, 이벤트 보낼 때 `t.event()`, 구간(`vision` · `router` · `agent` · `suggest` · `db.save_turn`), 끝에 `t.finish()` |
| `backend/agent.py` | config 에 `"callbacks": timing.callbacks()` (LangChain 버전이 맞으면 비어 있음 — 아래 참고) |
| `frontend/src/api.ts` | `streamChat` · `readSSE` 에 probe 몇 줄 |

---

## 2. 회사판에 옮기기

### 2-1. 서버 (필수)

1. `hub/timing.py` 를 그대로 복사한다 (Coris 다른 모듈에 기대지 않음).
2. `main.py`
   ```python
   from hub import timing
   # lifespan 안, yield 전
   timing.start_loop_monitor()
   # app 만든 뒤 — 다른 미들웨어보다 나중에 add 하면 가장 바깥이 된다
   app.add_middleware(timing.RequestStartMiddleware)
   ```
   > `@app.middleware("http")`(BaseHTTPMiddleware)로 만들지 않는다 — SSE 를 모아서 보내는 원인이 될 수 있다.
3. 채팅 endpoint
   ```python
   from fastapi import Request
   from hub import timing

   @router.post("/chat")
   async def chat(req: ChatRequest, request: Request, user=Depends(current_user)):
       t = timing.Timing("chat", t0=getattr(request.state, "t0", None), conv=conv_id, user=user_id)
       t.add("pre.request", timing.now() - t.t0)          # 본문 읽기 + 사용자 확인

       with t.span("db.load_conversation"):               # ← 회사판의 DB 읽기마다
           conv = ...

       async def generate():
           timing.activate(t)                              # 이 안의 LangChain LLM · tool 자동 기록
           ...
           t.event(ev["type"]); yield sse(ev)              # 화면으로 보내는 이벤트마다 (delta 포함)
           ...
           async with t.span("router"): plan = await ...
           async with t.span("suggest"): ...
           with t.span("db.save_turn"): ...                # ← 회사판의 DB 저장마다
           t.finish("ok")                                  # finally 에서
   ```
4. **DB 구간 이름은 `db.` 로 시작**하게 붙인다 — 합계(`db_ms`)에 들어간다.
   회사판이 **이벤트마다 저장**한다면 그 저장 호출을 `with t.span("db.save_event"):` 로 감싼다. 여러 번 불리면 `{"n": 횟수, "ms": 합계}` 로 모인다.
5. `generate()` 를 백그라운드 task 로 돌린다면(로컬의 `hub/runs.py` 처럼) `activate()` 는 **generate 안에서** 부른다 — 그래야 그 task 의 LLM 호출이 잡힌다.
6. 로그에 LLM 이 0회로 나오면 LangChain 버전 차이다. 그래프 실행 config 에 `"callbacks": timing.callbacks()` 를 넣는다 (Router · 추천 질문 호출에도 같은 방식).

### 2-2. 화면 (선택 — "서버 · 전송은 빠른데 화면만 느릴 때")

`frontend/src/timingProbe.ts` 복사 후, SSE 를 읽는 함수에:
```ts
const probe = startProbe();                 // fetch 전
probe.headers();                            // fetch 응답 직후
probe.read(이번 read 에서 나온 data: 줄 수);  // reader.read() 마다
probe.event(ev.type, ev.type === "meta" ? ev.conversation_id : undefined);  // 이벤트마다
probe.finish();                             // 끝 (finally)
```
꺼져 있으면 아무것도 하지 않는다 (`localStorage` 값이 없으면 빈 함수).

### 2-3. 스크립트

`scripts/measure_stream.py` 복사. `httpx` 만 필요. 회사판 요청 형식(본문 · 사용자 헤더)이 다르면 `measure()` 의 `body` 와 `-H` 를 맞춘다.

---

## 3. 측정 순서

1. 서버 `.env`: `TIMING=1`, `TIMING_LOG=data/timing.jsonl` → 재시작
2. 자주 느리다고 하는 질문 10개 정도를 `questions.txt` 에 한 줄씩 (단순 조회 · 여러 tool · 보고서형 섞어서)
3. **서버 직접 주소**로 한 번, **사용자가 쓰는 주소(프록시 경유)** 로 한 번
   ```bash
   python scripts/measure_stream.py --base http://<서버>:8000 -f questions.txt --repeat 2 --out data/direct.csv -H "X-User-Id: <id>"
   python scripts/measure_stream.py --base https://<사내 주소> -f questions.txt --repeat 2 --out data/proxy.csv -H "X-User-Id: <id>"
   ```
4. 브라우저에서 probe 를 켜고 같은 질문 몇 개 — 콘솔 표 확인
5. 서버 로그 `[timing]` 줄 · `data/timing.jsonl` 과 `conversation_id` 로 짝지어 비교

---

## 4. 결과 읽기

### 서버 로그 한 줄 (예시)
```
[timing 3f2a9c1d] chat cv_ab12 총 24.3s | 첫 글자 18.9s | LLM 5회 20.1s (gpt-4o 4회 18.7s, gpt-4o-mini 1회 1.4s)
 | tool 3회 2.6s | DB 0.1s | loop 멈춤 0회 최대 0.0s | delta 412개 최대 간격 0.3s
 | pre.request=0.0s db.load_conversation=0.0s db.skills=0.0s db.user_memory=0.0s router=1.4s agent=21.0s suggest=1.8s db.save_turn=0.0s
```
JSON(`TIMING_LOG`)에는 LLM 호출마다 `ms` · `first_token_ms`(첫 토큰까지) · `msgs`(메시지 수) · `in_chars`(입력 길이) · `tool_calls` 가 남는다.

### 스크립트 출력 (예시)
```
• HOLD Lot 현황 알려줘 (1/2) conv=cv_ab12
   헤더 0.0s · Router 1.4s · 첫 tool 3.0s · 첫 글자 18.9s · 마지막 글자 23.1s · 추천 24.3s · 끝 24.3s
   delta 412개 · 묶음 405개(최대 3개) · 최대 간격 0.3s · tool 3회 → 전송은 실시간
```
`묶음` 이 몇 개뿐이고 `최대` 가 delta 수에 가까우면 `⚠ 한꺼번에 도착` 으로 표시된다.

### 원인 찾기

| 보이는 것 | 원인 | 조치 |
|---|---|---|
| `loop 멈춤` 최대가 0.1초 이상 · 자주 | async 함수 안에서 **동기 DB 호출**(psycopg2 등)이나 무거운 계산이 서버를 붙잡음 — 그동안 **모든 사용자의 스트리밍이 멈춘다** | async 드라이버(asyncpg · psycopg3 async) 또는 `await asyncio.to_thread(...)`, 연결 풀 |
| `db_ms` 가 큼 · `db.save_event` 의 n 이 수백 | 이벤트(delta)마다 INSERT · commit | 답변이 끝난 뒤 한 번에 저장, 또는 모아서 일괄 저장 |
| `pre.request` 가 큼 | 인증 · 사용자 프로필 조회 · 사용자 upsert 가 느림 | 캐시, 비동기 처리 |
| LLM `first_token_ms` 가 큼 (호출마다 수 초) | 사내 LLM 게이트웨이 대기 · 모델 자체 | 게이트웨이 담당과 확인. 입력 줄이기 · 호출 수 줄이기 |
| `LLM n회` 가 많음 (agent 모델 4회 이상) | ReAct 순환 | 반복 차단 · 동시 호출(적용됨) → 하이브리드(계획 후 실행) |
| 같은 질문 안에서 `in_chars` 가 순환마다 크게 늘어남 | tool 결과가 쌓여 매번 다시 보냄 | 큰 결과 보관(offload) · 순환 중 결과 줄이기 |
| `suggest` 가 큼 | 답변 뒤 추천 질문 LLM 이 끝나야 '답변 중' 이 꺼짐 | 추천을 백그라운드로 · 먼저 완료 이벤트 보내기 |
| 서버 `첫 글자` 는 빠른데 스크립트(프록시 경유)가 늦거나 **⚠ 한꺼번에 도착** | 프록시 · gzip · 로드밸런서가 스트림을 모아 보냄 | nginx `proxy_buffering off;` · `gzip off`(text/event-stream), 사내 프록시 · WAF 설정 확인. 응답 헤더 `X-Accel-Buffering: no` · `Cache-Control: no-transform` 은 로컬에 이미 있음 — 회사판에도 있는지 확인 |
| 스크립트는 실시간인데 브라우저 probe `reads` 가 적고 `max_events_per_read` 가 큼 | 브라우저 쪽 경로(개발 서버 프록시 · 사내 프록시 PAC)에서 모음 | 화면이 붙는 주소의 프록시 설정 확인 |
| 브라우저 probe 는 실시간인데 `longtask_ms` 가 큼 | **화면 그리기** — 글자 조각이 올 때마다 답변 전체를 마크다운으로 다시 그림(길수록 느려짐) | 화면 갱신을 프레임 단위로 묶기(requestAnimationFrame), 끝난 문단만 마크다운 처리 |

### 여러 건 집계
```bash
python - <<'EOF'
import json, statistics as st
rows = [json.loads(l) for l in open("data/timing.jsonl", encoding="utf-8")]
for k in ("total_ms", "first_delta_ms", "llm_ms", "llm_n", "tool_ms", "db_ms", "loop_stall_max_ms"):
    v = [r[k] for r in rows if r.get(k) is not None]
    print(f"{k:18} 중앙 {st.median(v):>8} · 최대 {max(v):>8} · n={len(v)}")
EOF
```

---

## 5. 참고 · 한계

- 측정 자체의 부담은 작다 (콜백은 스레드를 거치지 않고 바로 기록, loop 감시는 50ms 마다 한 번 깨는 정도). 다 보면 `TIMING=0`.
- loop 멈춤은 50ms 단위로 본다 — 짧게 자주 막히는 것은 합계(`loop_stall_sum_ms`)로 본다. 서버 전체 값이라 동시에 다른 질문이 있으면 그 영향도 섞인다.
- `in_chars` 는 메시지 길이만 — tool 정의 길이는 들어가지 않는다. 토큰 수(`in_tok` · `out_tok`)는 스트리밍에서 게이트웨이가 usage 를 돌려줄 때만 나온다.
- 서버 시각은 "서버가 이벤트를 만든 시각", 스크립트 · probe 는 "도착한 시각"이다. 둘의 차이가 전송 구간이다.
- uvicorn worker 1개 기준. worker 가 여러 개면 loop 멈춤은 worker 마다 따로다.
- 로컬 확인: 가짜 LLM 으로 LLM · tool · DB 구간 · 서버 멈춤(동기 0.3초 → 0.32초로 잡힘) 기록, 가짜 SSE 서버로 "실시간 / 한꺼번에 도착" 구분을 확인했다. 실제 LLM 을 붙인 전체 흐름은 회사에서 처음 재게 된다.
