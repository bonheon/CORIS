"""
채팅 스트림 도착 시각 측정 — 브라우저 없이 /api/chat 에 질문을 보내고 이벤트가 닿는 시각을 잰다 (docs/TIMING.md).

서버 로그의 [timing] 과 conversation_id 로 짝지어 비교한다.
  서버 first_delta ≈ 여기 first_delta  → 전송은 실시간. 느리면 서버(LLM · DB) 쪽
  서버는 빠른데 여기서 늦게 · 한꺼번에  → 중간(프록시 · gzip · 로드밸런서)이 모아서 보낸다
  여기서는 실시간인데 화면만 느림      → 화면 그리기 (frontend/src/timingProbe.ts 로 확인)

쓰는 법 (backend 폴더에서, 서버가 떠 있을 때)
  python scripts/measure_stream.py -q "HOLD Lot 현황 알려줘"
  python scripts/measure_stream.py -f questions.txt --repeat 3 --out data/stream_timing.csv
  python scripts/measure_stream.py --base https://coris.company -H "X-User-Id: hong.gd" -q "..."
  # 사내 프록시를 거치는 주소와 서버 직접 주소(:8000)를 같은 질문으로 각각 재면 중간 구간 영향이 보인다
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

import httpx

BURST_MS = 20   # 이 간격 안에 붙어 온 delta 는 '한꺼번에 온 묶음' 으로 본다


def measure(base: str, question: str, headers: dict, timeout: float) -> dict:
    body = {"messages": [{"role": "user", "content": question}]}
    t0 = time.perf_counter()
    ms = lambda: round((time.perf_counter() - t0) * 1000)  # noqa: E731
    row = {"question": question[:60], "conv": None, "status": None, "headers_ms": None, "first_byte_ms": None,
           "route_ms": None, "first_tool_ms": None, "first_delta_ms": None, "last_delta_ms": None,
           "suggest_ms": None, "done_ms": None, "deltas": 0, "tools": 0, "max_gap_ms": 0,
           "bursts": 0, "max_burst": 0, "error": None}
    arrivals: list = []
    with httpx.Client(timeout=httpx.Timeout(timeout, read=timeout)) as c:
        with c.stream("POST", base.rstrip("/") + "/api/chat", json=body, headers=headers) as r:
            row["status"] = r.status_code
            row["headers_ms"] = ms()
            if r.status_code != 200:
                row["error"] = r.read().decode("utf-8", "replace")[:200]
                return row
            for line in r.iter_lines():
                if row["first_byte_ms"] is None:
                    row["first_byte_ms"] = ms()
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    row["done_ms"] = ms()
                    break
                try:
                    ev = json.loads(data)
                except json.JSONDecodeError:
                    continue
                typ = ev.get("type")
                if typ == "meta":
                    row["conv"] = ev.get("conversation_id")
                elif typ == "route" and row["route_ms"] is None:
                    row["route_ms"] = ms()
                elif typ == "tool_start":
                    row["tools"] += 1
                    if row["first_tool_ms"] is None:
                        row["first_tool_ms"] = ms()
                elif typ == "delta":
                    t = ms()
                    arrivals.append(t)
                    if row["first_delta_ms"] is None:
                        row["first_delta_ms"] = t
                    row["last_delta_ms"] = t
                elif typ == "suggestions":
                    row["suggest_ms"] = ms()
                elif typ == "error":
                    row["error"] = ev.get("message", "")[:200]
    row["deltas"] = len(arrivals)
    if arrivals:
        gaps = [b - a for a, b in zip(arrivals, arrivals[1:])]
        row["max_gap_ms"] = max(gaps, default=0)
        bursts, size = [], 1
        for g in gaps:
            if g <= BURST_MS:
                size += 1
            else:
                bursts.append(size)
                size = 1
        bursts.append(size)
        row["bursts"], row["max_burst"] = len(bursts), max(bursts)
    return row


def verdict(row: dict) -> str:
    if row["error"]:
        return "오류"
    n, b = row["deltas"], row["bursts"]
    if n >= 30 and (b <= 3 or row["max_burst"] >= n * 0.5):
        return "⚠ 한꺼번에 도착 — 중간에서 모아 보내는 것으로 보임"
    if row["first_delta_ms"] and row["first_delta_ms"] > 10000:
        return "첫 글자까지 10초 이상 — 서버 [timing] 에서 어디가 긴지 확인"
    return "전송은 실시간"


def _sec(v) -> str:
    return "-" if v is None else f"{v / 1000:.1f}s"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://localhost:8000", help="백엔드 주소 (프록시 주소로도 재 볼 것)")
    ap.add_argument("-q", "--question", action="append", default=[], help="질문 (여러 번 줄 수 있음)")
    ap.add_argument("-f", "--file", help="질문 파일 — 한 줄에 하나")
    ap.add_argument("--repeat", type=int, default=1, help="질문마다 반복 횟수")
    ap.add_argument("-H", "--header", action="append", default=[], help='추가 헤더 "이름: 값" (사용자 id 등)')
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--out", help="결과 CSV 경로")
    a = ap.parse_args()

    questions = list(a.question)
    if a.file:
        questions += [x.strip() for x in Path(a.file).read_text(encoding="utf-8").splitlines() if x.strip()]
    if not questions:
        ap.error("-q 또는 -f 로 질문을 주세요")
    headers = {}
    for h in a.header:
        k, _, v = h.partition(":")
        headers[k.strip()] = v.strip()

    rows = []
    for q in questions:
        for i in range(a.repeat):
            try:
                row = measure(a.base, q, headers, a.timeout)
            except httpx.HTTPError as e:
                print(f"✗ {q[:40]} — {type(e).__name__}: {e}")
                rows.append({"question": q[:60], "error": f"{type(e).__name__}: {e}"[:200]})
                continue
            rows.append(row)
            print(f"• {row['question'][:40]} ({i + 1}/{a.repeat}) conv={row['conv']}\n"
                  f"   헤더 {_sec(row['headers_ms'])} · Router {_sec(row['route_ms'])} · 첫 tool {_sec(row['first_tool_ms'])}"
                  f" · 첫 글자 {_sec(row['first_delta_ms'])} · 마지막 글자 {_sec(row['last_delta_ms'])}"
                  f" · 추천 {_sec(row['suggest_ms'])} · 끝 {_sec(row['done_ms'])}\n"
                  f"   delta {row['deltas']}개 · 묶음 {row['bursts']}개(최대 {row['max_burst']}개) · 최대 간격 {_sec(row['max_gap_ms'])}"
                  f" · tool {row['tools']}회 → {verdict(row)}")

    if a.out and rows:
        p = Path(a.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        keys = list(dict.fromkeys(k for r in rows for k in r))
        with p.open("w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig — 엑셀에서 한글이 깨지지 않게
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
        print(f"\n저장: {p}")


if __name__ == "__main__":
    sys.exit(main())
