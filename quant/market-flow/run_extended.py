# -*- coding: utf-8 -*-
"""
Flow Radar - 확장 검증

1차 검증에서 드러난 세 가지 문제를 정면으로 다룬다.

  문제 1  한국 표본이 9.8년뿐이라 2008년 금융위기가 없다
     -> KOSPI 현물지수로 앞(1997~2014)뒤(2024~2025)를 이어 27.7년으로 확장.
        1997 외환위기 후반, 2000 닷컴붕괴, 2008 금융위기, 2020 코로나가 모두 들어온다.

  문제 2  RISK 층의 IC가 두 시장 모두 -0.10 (부호가 반대)
     -> 사람이 보고 손으로 뒤집으면 데이터 스누핑이다. 대신 '과거 IC를 보고
        규칙이 스스로 부호를 정하는' 동적 가중치를 넣고, 그것이 스스로
        RISK 를 뒤집는지 확인한다.

  문제 3  V0(월말)이 벤치마크에 못 미쳤고, 개선안은 결과를 본 뒤 나왔다
     -> 파라미터를 완전히 고정한 채 설계에 쓰지 않은 두 구간에서 다시 잰다.
        후향 OOS 1997-2014 (16.7년) / 전향 OOS 2024.04-2025.03 (1.0년)

산출물: results/extended_*.csv
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from flow_radar import (
    KOSPI_CFG, KOSPI_LONG_CFG, KOSPI_US10_CFG, SP500_CFG, LAYERS, REGIME_LABELS,
    backtest, build_signals, load_panel, perf_stats, score_frame,
    to_regime, to_weight,
)
from run_backtest import RES, save, HI, LO, W_ON, W_MID, W_OFF, COST_BP

# 1차 검증에서 쓴 값 그대로. 아래에서 단 하나도 바꾸지 않는다.
CASH = 0.02

PERIODS = [
    ("후향 OOS 1997-2014", "1997-07-01", "2014-03-12"),
    ("  ├ 전반 1997-2003", "1997-07-01", "2003-12-31"),
    ("  └ 후반 2004-2014", "2004-01-01", "2014-03-12"),
    ("설계표본 2014-2024", "2014-03-13", "2024-03-29"),
    ("전향 OOS 2024-2025", "2024-04-01", "2025-03-20"),
]


def prep(panel, raw_panel, cfg, dynamic: bool):
    """지표 계산 → 해당 시장의 실제 거래일만 남김."""
    sig = build_signals(panel, cfg)
    cal = raw_panel[cfg.equity].dropna().index
    price_full = panel[cfg.equity]
    sc = score_frame(sig, cfg, price=price_full, dynamic=dynamic)
    sc = sc.loc[cfg.start:cfg.end].dropna(subset=["FLOW_SCORE"])
    sc = sc.loc[sc.index.isin(cal)]
    return sc, price_full.reindex(sc.index)


def run(panel, raw_panel, cfg, dynamic: bool, freq: str):
    sc, price = prep(panel, raw_panel, cfg, dynamic)
    w = to_weight(to_regime(sc["FLOW_SCORE"], HI, LO), W_ON, W_MID, W_OFF)
    return sc, price, backtest(price, w, freq=freq, cost_bp=COST_BP, cash_yield=CASH)


def row(tag, r, extra=None):
    s = r.stats
    out = {"구분": tag,
           "CAGR(%)": round(s["CAGR"] * 100, 2),
           "변동성(%)": round(s["변동성"] * 100, 2),
           "샤프": s["샤프"],
           "MDD(%)": round(s["MDD"] * 100, 2),
           "칼마": s["칼마(CAGR/|MDD|)"],
           "연수": s["관측연수"]}
    if extra:
        out.update(extra)
    return out


# ---------------------------------------------------------------------------

def main() -> int:
    panel, raw_panel = load_panel()

    # ---- A. 27년 한국 표본, 정적 vs 동적 x 월말 vs 주말 --------------------
    print("#" * 78)
    print("A. 한국 27.7년 (1997-07 ~ 2025-03) - 파라미터 고정, 규칙만 교체")
    print("#" * 78)
    rows, curves = [], {}
    for dyn in (False, True):
        for freq in ("M", "W"):
            sc, price, r = run(panel, raw_panel, KOSPI_LONG_CFG, dyn, freq)
            tag = f"{'동적' if dyn else '정적'} 가중 x {'주말' if freq=='W' else '월말'}"
            rows.append(row(tag, r, {"회전율": r.stats["연회전율(편도)"]}))
            curves[tag] = (sc, price, r)
    bh = perf_stats(curves[list(curves)[0]][1].pct_change().fillna(0.0))
    rows.append({"구분": "단순보유", "CAGR(%)": round(bh["CAGR"] * 100, 2),
                 "변동성(%)": round(bh["변동성"] * 100, 2), "샤프": bh["샤프"],
                 "MDD(%)": round(bh["MDD"] * 100, 2), "칼마": bh["칼마(CAGR/|MDD|)"],
                 "연수": bh["관측연수"], "회전율": 0.0})
    A = pd.DataFrame(rows)
    print(A.to_string(index=False))
    save(A.set_index("구분"), "extended_A_korea27y.csv")

    # ---- B. 동적 규칙이 실제로 RISK 층을 뒤집었나 --------------------------
    print("\n" + "#" * 78)
    print("B. 동적 규칙이 각 층에 매긴 부호 (관측일 비중 %)")
    print("#" * 78)
    sc_dyn = curves["동적 가중 x 주말"][0]
    sgn_rows = []
    for layer in LAYERS:
        s = sc_dyn[f"SGN.{layer}"]
        sgn_rows.append({
            "층": layer,
            "그대로(+1) %": round(float((s == 1).mean()) * 100, 1),
            "쉼(0) %": round(float((s == 0).mean()) * 100, 1),
            "뒤집음(-1) %": round(float((s == -1).mean()) * 100, 1),
            "최근 부호": int(s.iloc[-1]),
        })
    B = pd.DataFrame(sgn_rows)
    print(B.to_string(index=False))
    save(B.set_index("층"), "extended_B_layer_signs.csv")

    # ---- C. 구간별 성과 (설계표본 / 후향 OOS / 전향 OOS) -------------------
    print("\n" + "#" * 78)
    print("C. 구간별 성과 - 설계에 쓰지 않은 구간에서도 유지되는가")
    print("#" * 78)
    crows = []
    for label, s0, s1 in PERIODS:
        for tag in ("정적 가중 x 월말", "정적 가중 x 주말", "동적 가중 x 주말"):
            _, _, r = curves[tag]
            ec = r.equity_curve.loc[s0:s1]
            if len(ec) < 60:
                continue
            st = perf_stats(ec["strategy_ret"])
            bn = perf_stats(ec["bench_ret"])
            crows.append({
                "구간": label, "규칙": tag,
                "전략 CAGR(%)": round(st["CAGR"] * 100, 2),
                "보유 CAGR(%)": round(bn["CAGR"] * 100, 2),
                "초과(%p)": round((st["CAGR"] - bn["CAGR"]) * 100, 2),
                "전략 샤프": st["샤프"], "보유 샤프": bn["샤프"],
                "전략 MDD(%)": round(st["MDD"] * 100, 2),
                "보유 MDD(%)": round(bn["MDD"] * 100, 2),
            })
    C = pd.DataFrame(crows)
    print(C.to_string(index=False))
    save(C.set_index(["구간", "규칙"]), "extended_C_periods.csv")

    # ---- D. 위기 구간별 방어력 ---------------------------------------------
    print("\n" + "#" * 78)
    print("D. 위기 구간 방어력 (전 구간 파라미터 동일)")
    print("#" * 78)
    crises = [
        ("닷컴붕괴 2000.01-2001.09", "2000-01-01", "2001-09-30"),
        ("금융위기 2007.11-2009.03", "2007-11-01", "2009-03-31"),
        ("차이나쇼크 2015.06-2016.02", "2015-06-01", "2016-02-29"),
        ("코로나 2020.02-2020.03", "2020-02-01", "2020-03-31"),
        ("긴축 2022.01-2022.10", "2022-01-01", "2022-10-31"),
    ]
    drows = []
    for name, s0, s1 in crises:
        for tag in ("정적 가중 x 주말", "동적 가중 x 주말"):
            _, _, r = curves[tag]
            ec = r.equity_curve.loc[s0:s1]
            if ec.empty:
                continue
            drows.append({
                "위기": name, "규칙": tag,
                "전략(%)": round(float((1 + ec["strategy_ret"]).prod() - 1) * 100, 1),
                "보유(%)": round(float((1 + ec["bench_ret"]).prod() - 1) * 100, 1),
                "평균비중(%)": round(float(ec["weight"].mean()) * 100, 0),
            })
    D = pd.DataFrame(drows)
    print(D.to_string(index=False))
    save(D.set_index(["위기", "규칙"]), "extended_D_crisis.csv")

    # ---- E. 국채 대체(KR10 -> US10)가 결과를 바꾸는가 ----------------------
    print("\n" + "#" * 78)
    print("E. 대조군 - 장기 설정이 쓰는 US10 국채가 결과를 왜곡하지 않는지")
    print("#" * 78)
    erows = []
    for cfg, name in ((KOSPI_CFG, "2014-24 · 국채 KR10 (원본)"),
                      (KOSPI_US10_CFG, "2014-24 · 국채 US10 (장기설정과 동일)")):
        _, _, r = run(panel, raw_panel, cfg, False, "W")
        erows.append(row(name, r))
    E = pd.DataFrame(erows)
    print(E.to_string(index=False))
    save(E.set_index("구분"), "extended_E_bond_swap.csv")

    # ---- F. 미국 34년에도 동적 가중이 통하는가 -----------------------------
    print("\n" + "#" * 78)
    print("F. 미국 S&P500 1990-2024 - 같은 수정이 다른 시장에서도 통하는가")
    print("#" * 78)
    frows = []
    for dyn in (False, True):
        for freq in ("M", "W"):
            _, price, r = run(panel, raw_panel, SP500_CFG, dyn, freq)
            frows.append(row(f"{'동적' if dyn else '정적'} x {'주말' if freq=='W' else '월말'}", r))
    b = perf_stats(panel[SP500_CFG.equity].loc[SP500_CFG.start:SP500_CFG.end]
                   .dropna().pct_change().fillna(0.0))
    frows.append({"구분": "단순보유", "CAGR(%)": round(b["CAGR"] * 100, 2),
                  "변동성(%)": round(b["변동성"] * 100, 2), "샤프": b["샤프"],
                  "MDD(%)": round(b["MDD"] * 100, 2), "칼마": b["칼마(CAGR/|MDD|)"],
                  "연수": b["관측연수"]})
    F = pd.DataFrame(frows)
    print(F.to_string(index=False))
    save(F.set_index("구분"), "extended_F_sp500.csv")

    # ---- G. 전향 OOS 실패 진단 --------------------------------------------
    print("\n" + "#" * 78)
    print("G. 전향 OOS(2024.04-2025.03) 진단 - 월간 대체 데이터가 신호를 오염시켰나")
    print("#" * 78)
    sc_s = curves["정적 가중 x 주말"][0]
    oos = sc_s.loc["2024-04-01":"2025-03-20"]
    ins = sc_s.loc["2014-03-13":"2024-03-29"]
    g1 = pd.DataFrame({
        "설계표본 평균": ins[LAYERS + ["FLOW_SCORE"]].mean().round(3),
        "전향OOS 평균": oos[LAYERS + ["FLOW_SCORE"]].mean().round(3),
        "설계표본 표준편차": ins[LAYERS].reindex(columns=LAYERS + ["FLOW_SCORE"]).std().round(3),
        "전향OOS 표준편차": oos[LAYERS].reindex(columns=LAYERS + ["FLOW_SCORE"]).std().round(3),
    })
    print(g1.to_string())
    save(g1, "extended_G1_oos_layers.csv")

    # COST 층(월간 대체가 들어간 유일한 층)을 빼면 결과가 달라지는가
    sig = build_signals(panel, KOSPI_LONG_CFG)
    cal = raw_panel[KOSPI_LONG_CFG.equity].dropna().index
    price_full = panel[KOSPI_LONG_CFG.equity]
    sub = {"4층 전체": LAYERS,
           "COST 제외(3층)": ["TREND", "RISK", "FLOW"],
           "TREND+FLOW 만": ["TREND", "FLOW"]}
    g2 = []
    for name, keep in sub.items():
        L = pd.DataFrame({k: sig[[c for c in sig.columns if c.startswith(k + ".")]].mean(axis=1)
                          for k in keep})
        w = KOSPI_LONG_CFG.layer_weights
        score = sum(L[k] * w[k] for k in keep) / sum(w[k] for k in keep)
        score = score.loc[KOSPI_LONG_CFG.start:KOSPI_LONG_CFG.end].dropna()
        score = score.loc[score.index.isin(cal)]
        pr = price_full.reindex(score.index)
        wt = to_weight(to_regime(score, HI, LO), W_ON, W_MID, W_OFF)
        r = backtest(pr, wt, freq="W", cost_bp=COST_BP, cash_yield=CASH)
        ec = r.equity_curve
        for label, s0, s1 in PERIODS:
            seg = ec.loc[s0:s1]
            if len(seg) < 60:
                continue
            st, bn = perf_stats(seg["strategy_ret"]), perf_stats(seg["bench_ret"])
            g2.append({"신호구성": name, "구간": label,
                       "전략 CAGR(%)": round(st["CAGR"] * 100, 2),
                       "보유 CAGR(%)": round(bn["CAGR"] * 100, 2),
                       "초과(%p)": round((st["CAGR"] - bn["CAGR"]) * 100, 2),
                       "샤프": st["샤프"], "평균비중(%)": round(float(seg["weight"].mean()) * 100, 0)})
    G2 = pd.DataFrame(g2)
    print()
    print(G2.to_string(index=False))
    save(G2.set_index(["신호구성", "구간"]), "extended_G2_layer_subsets.csv")

    # ---- H. 전향 OOS 실패는 얼마나 이례적인가 ------------------------------
    print("\n" + "#" * 78)
    print("H. 롤링 1년 초과수익 분포 - 전향 OOS 실패가 전례 없는 일인가")
    print("#" * 78)
    hrows = []
    for tag in ("정적 가중 x 월말", "정적 가중 x 주말"):
        ec = curves[tag][2].equity_curve
        win = 252
        cs = (1 + ec["strategy_ret"]).rolling(win).apply(np.prod, raw=True) - 1
        cb = (1 + ec["bench_ret"]).rolling(win).apply(np.prod, raw=True) - 1
        ex = (cs - cb).dropna()
        oos_ex = float(ex.loc["2024-04-01":"2025-03-20"].min()) if len(
            ex.loc["2024-04-01":"2025-03-20"]) else np.nan
        end_ex = float(ex.iloc[-1])
        hrows.append({
            "규칙": tag,
            "롤링1년 초과 중앙값(%p)": round(float(ex.median()) * 100, 2),
            "이긴 비율(%)": round(float((ex > 0).mean()) * 100, 1),
            "최악 1년(%p)": round(float(ex.min()) * 100, 2),
            "최고 1년(%p)": round(float(ex.max()) * 100, 2),
            "전향OOS 종료시점(%p)": round(end_ex * 100, 2),
            "그 값의 백분위(%)": round(float((ex < end_ex).mean()) * 100, 1),
        })
    H = pd.DataFrame(hrows)
    print(H.to_string(index=False))
    save(H.set_index("규칙"), "extended_H_rolling1y.csv")
    print("\n  읽는 법: '백분위'가 낮을수록 이례적으로 나쁜 구간이다.")
    print("  0%에 가까우면 전례 없는 실패, 10~30%면 과거에도 겪던 수준의 부진이다.")

    # ---- I. 27.5년 표본에서 다시 잰 정보계수 -------------------------------
    print("\n" + "#" * 78)
    print("I. 층별 정보계수 재측정 - 10년이 아니라 27.5년 표본에서")
    print("#" * 78)
    sc_i, pr_i = prep(panel, raw_panel, KOSPI_LONG_CFG, False)
    irows = []
    for col in LAYERS + ["FLOW_SCORE"]:
        row_i = {"지표": col}
        for h in (1, 5, 20, 60, 120):
            fwd = pr_i.shift(-h) / pr_i - 1.0
            row_i[f"IC_{h}일"] = round(float(sc_i[col].corr(fwd, method="spearman")), 4)
        irows.append(row_i)
    I = pd.DataFrame(irows)
    print(I.to_string(index=False))
    save(I.set_index("지표"), "extended_I_ic_27y.csv")

    # 곡선 저장 (차트용)
    for tag in ("정적 가중 x 주말", "동적 가중 x 주말"):
        _, _, r = curves[tag]
        key = "static" if tag.startswith("정적") else "dynamic"
        save(r.equity_curve.round(6), f"extended_curve_{key}.csv")

    print(f"\n결과 저장 -> {RES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
