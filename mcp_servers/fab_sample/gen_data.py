"""
샘플 데이터 생성 — Lot 공정 진행 이력 · 장비별 일 효율 (각 약 1,000행, seed 고정이라 매번 같은 값).

    python gen_data.py          # data/lot_history.csv · data/eqp_efficiency.csv 생성

심어 둔 이상 패턴 (질문 테스트용):
  - ETCH-03 : 11/04~11/07 BM(고장)으로 가동률 급락, 그 기간 ETCH 공정 대기 시간 증가
  - CVD-02  : 10/20 이후 WPH(시간당 처리 wafer) 가 서서히 하락
  - PHOTO-02: 주말마다 PM(정기 보전)
  - HOLD: 풀린 이력(hold_reason · hold_min) 과 현재 HOLD 중인 Lot, 진행 중(RUNNING) · 대기(WAIT) Lot 포함
"""
import csv
import random
from datetime import date, datetime, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent / "data"
SEED = 20261119

# 공정 순서: (step_seq, step_name, area, 기준 처리 시간 분)
FLOW = [
    (100, "WAFER START", "WET", 30), (200, "PRE CLEAN", "WET", 45), (300, "GATE OXIDATION", "DIFF", 240),
    (400, "POLY DEPO", "CVD", 150), (500, "GATE PHOTO", "PHOTO", 70), (600, "GATE ETCH", "ETCH", 90),
    (700, "ASH STRIP", "WET", 40), (800, "LDD IMPLANT", "IMP", 60), (900, "SPACER DEPO", "CVD", 120),
    (1000, "SPACER ETCH", "ETCH", 80), (1100, "S/D IMPLANT", "IMP", 70), (1200, "RTA ANNEAL", "DIFF", 50),
    (1300, "ILD DEPO", "CVD", 140), (1400, "ILD CMP", "CMP", 75), (1500, "CONTACT PHOTO", "PHOTO", 70),
    (1600, "CONTACT ETCH", "ETCH", 100), (1700, "METAL1 DEPO", "PVD", 110), (1800, "FINAL INSP", "MEAS", 35),
]
EQPS = {
    "WET": ["WET-01", "WET-02", "WET-03"], "DIFF": ["DIFF-01", "DIFF-02", "DIFF-03"],
    "CVD": ["CVD-01", "CVD-02", "CVD-03"], "PHOTO": ["PHOTO-01", "PHOTO-02", "PHOTO-03"],
    "ETCH": ["ETCH-01", "ETCH-02", "ETCH-03", "ETCH-04"], "IMP": ["IMP-01", "IMP-02"],
    "CMP": ["CMP-01", "CMP-02"], "PVD": ["PVD-01", "PVD-02"], "MEAS": ["MEAS-01", "MEAS-02"],
}
WPH_BASE = {"WET": 120, "DIFF": 100, "CVD": 45, "PHOTO": 80, "ETCH": 40, "IMP": 60, "CMP": 35, "PVD": 50, "MEAS": 150}
PRODUCTS = {"DRAM-16G": "D16", "NAND-1T": "N1T", "LOGIC-5N": "L5N"}
HOLD_REASONS = ["CD 규격 이탈 (OOS)", "파티클 다발", "장비 알람 후 재확인 필요", "막 두께 Trend 이상", "Recipe 불일치"]

ETCH03_DOWN = (date(2026, 11, 4), date(2026, 11, 7))
LOT_GAP_H = 13
EFF_START, EFF_END = date(2026, 10, 8), date(2026, 11, 18)   # 24대 × 42일 = 1,008행


def lot_history(rnd: random.Random) -> list[dict]:
    rows = []
    start0 = datetime(2026, 10, 15, 6, 0)
    now = datetime(2026, 11, 19, 9, 0)   # 데이터 기준 시각
    lot_no = 0
    while True:   # Lot 투입 간격 LOT_GAP_H 시간 — 기준 시각까지 투입된 Lot 전부
        lot_no += 1
        t = start0 + timedelta(hours=lot_no * LOT_GAP_H + rnd.randint(0, 6))
        if t > now:
            break
        product = rnd.choice(list(PRODUCTS))
        lot_id = f"{PRODUCTS[product]}{lot_no:04d}.1"
        qty = rnd.choice([25, 25, 25, 24, 23])
        hold_at = rnd.choice(FLOW[3:15])[0] if rnd.random() < 0.25 else None
        if t > now - timedelta(days=5) and rnd.random() < 0.5:   # 최근 투입 Lot — 앞쪽 step 에서 HOLD (현재 HOLD 재공)
            hold_at = rnd.choice(FLOW[1:5])[0]
        for seq, step, area, base in FLOW:
            eqp = rnd.choice(EQPS[area])
            wait = rnd.randint(30, 600)
            if area == "ETCH" and ETCH03_DOWN[0] <= t.date() <= ETCH03_DOWN[1]:
                wait += rnd.randint(240, 600)   # ETCH-03 고장 기간 — 다른 ETCH 장비로 몰려 대기 증가
                eqp = rnd.choice(["ETCH-01", "ETCH-02", "ETCH-04"])
            proc = round(base * rnd.uniform(0.85, 1.25))
            if eqp == "CVD-02" and t.date() > date(2026, 10, 20):
                proc = round(proc * (1 + (t.date() - date(2026, 10, 20)).days * 0.008))
            track_in = t + timedelta(minutes=wait)
            track_out = track_in + timedelta(minutes=proc)
            recipe = f"{area}_{step.split()[0][:4]}_{PRODUCTS[product]}_V{rnd.randint(1, 3)}"
            row = {"lot_id": lot_id, "product": product, "step_seq": seq, "step_name": step, "area": area,
                   "eqp_id": eqp, "recipe": recipe, "qty": qty, "wait_min": wait, "proc_min": proc,
                   "track_in": track_in.isoformat(timespec="minutes"), "track_out": track_out.isoformat(timespec="minutes"),
                   "status": "DONE", "hold_reason": "", "hold_min": ""}
            if track_in > now:   # 아직 도착 안 한 step — 대기 1건만 남기고 이 Lot 은 끝
                rows.append(row | {"eqp_id": "", "recipe": "", "proc_min": "", "track_in": "", "track_out": "",
                                   "wait_min": "", "status": "WAIT"})
                break
            if track_out > now:
                rows.append(row | {"track_out": "", "proc_min": "", "status": "RUNNING"})
                break
            if seq == hold_at:   # step 완료 후 HOLD — 풀렸으면 이력(hold_min)만 남기고 진행, 아직이면 HOLD 로 멈춤
                reason, hold = rnd.choice(HOLD_REASONS), rnd.randint(240, 5760)
                if track_out + timedelta(minutes=hold) > now:
                    rows.append(row | {"status": "HOLD", "hold_reason": reason})
                    break
                row |= {"hold_reason": reason, "hold_min": hold}
                track_out += timedelta(minutes=hold)
            rows.append(row)
            t = track_out
    return rows


def eqp_efficiency(rnd: random.Random) -> list[dict]:
    rows = []
    d = EFF_START
    while d <= EFF_END:
        for area, eqps in EQPS.items():
            for eqp in eqps:
                pm = 0.0
                bm = round(rnd.choice([0, 0, 0, 0, 0.5, 1.0, 1.5]), 1)
                if eqp == "PHOTO-02" and d.weekday() == 5:
                    pm = 6.0
                elif rnd.random() < 0.05:
                    pm = round(rnd.uniform(2, 5), 1)
                if eqp == "ETCH-03" and ETCH03_DOWN[0] <= d <= ETCH03_DOWN[1]:
                    bm = round(rnd.uniform(16, 22), 1)
                down = round(pm + bm, 1)
                avail = 24 - down
                run = round(min(avail, avail * rnd.uniform(0.72, 0.93)), 1)
                idle = round(avail - run, 1)
                wph = WPH_BASE[area] * rnd.uniform(0.9, 1.08)
                if eqp == "CVD-02" and d > date(2026, 10, 20):
                    wph *= 1 - (d - date(2026, 10, 20)).days * 0.009
                wph = round(wph, 1)
                wafers = int(run * wph)
                availability = round(avail / 24 * 100, 1)
                utilization = round(run / 24 * 100, 1)
                perf = min(1.0, wph / WPH_BASE[area])
                quality = rnd.uniform(0.97, 0.998)
                oee = round(run / 24 * perf * quality * 100, 1)
                rows.append({"date": d.isoformat(), "eqp_id": eqp, "area": area, "run_hr": run, "idle_hr": idle,
                             "pm_hr": pm, "bm_hr": bm, "down_hr": down, "availability_pct": availability,
                             "utilization_pct": utilization, "wph": wph, "wafers_out": wafers, "oee_pct": oee})
        d += timedelta(days=1)
    return rows


def write(name: str, rows: list[dict]) -> None:
    OUT.mkdir(exist_ok=True)
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{name}: {len(rows)} rows")


if __name__ == "__main__":
    write("lot_history.csv", lot_history(random.Random(SEED)))
    write("eqp_efficiency.csv", eqp_efficiency(random.Random(SEED + 1)))
