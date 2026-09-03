# -*- coding: utf-8 -*-
"""
Flow Radar 백테스트 실행기

  python3 run_backtest.py

산출물 (results/)
  - {시장}_signals.csv     : 일자별 층 점수 / Flow Score / 레짐 / 비중
  - {시장}_equity.csv      : 전략·벤치마크 누적곡선
  - summary.csv            : 시장별 성과 요약
  - sensitivity.csv        : 임계값·비용·리밸런싱주기 민감도
  - walkforward.csv        : 전·후반 분할 검증
  - regime_stats.csv       : 레짐별 실제 다음날 수익률 분포 (신호 유효성 검증)
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from flow_radar import (
    KOSPI_CFG, SP500_CFG, LAYERS, REGIME_LABELS,
    backtest, build_signals, load_panel, perf_stats, score_frame,
    to_regime, to_weight,
)

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
os.makedirs(RES, exist_ok=True)

# 사전 고정 파라미터 (백테스트 결과를 보고 조정하지 않는다)
HI, LO = 0.20, -0.20         # 레짐 임계값 (시그마)
W_ON, W_MID, W_OFF = 1.0, 0.5, 0.0
FREQ = "M"                   # 월말 리밸런싱
COST_BP = 10.0               # 편도 10bp (국내 ETF 실거래 수준)
CASH_YIELD = 0.0             # 현금 이자 0 - 보수적 가정


def save(df: pd.DataFrame, name: str) -> None:
    df.to_csv(os.path.join(RES, name), encoding="utf-8-sig")


def prep(panel: pd.DataFrame, raw_panel: pd.DataFrame, cfg):
    """
    지표는 채워진 패널로 계산하되, 백테스트는 해당 시장의 실제 거래일에서만 한다.
    (한국 휴장일에 미국 데이터로 만들어진 가짜 거래일을 제거)
    """
    sig = build_signals(panel, cfg)
    sc = score_frame(sig, cfg).loc[cfg.start:cfg.end].dropna(subset=["FLOW_SCORE"])
    cal = raw_panel[cfg.equity].dropna().index           # 진짜 거래일
    sc = sc.loc[sc.index.isin(cal)]
    price = panel[cfg.equity].reindex(sc.index)
    return sc, price


def fmt(stats: dict) -> dict:
    out = dict(stats)
    for k in ("CAGR", "변동성", "MDD", "월간승률"):
        if k in out:
            out[k] = f"{out[k]*100:.2f}%"
    return out


def run_market(panel: pd.DataFrame, raw_panel: pd.DataFrame, cfg, tag: str) -> dict:
    sc, price = prep(panel, raw_panel, cfg)
    regime = to_regime(sc["FLOW_SCORE"], HI, LO)
    weight = to_weight(regime, W_ON, W_MID, W_OFF)

    r = backtest(price, weight, freq=FREQ, cost_bp=COST_BP,
                 cash_yield=CASH_YIELD)

    out = sc[LAYERS + ["FLOW_SCORE"]].copy()
    out["레짐"] = regime.map(REGIME_LABELS)
    out["목표비중"] = weight
    out["실제비중"] = r.equity_curve["weight"]
    out["종가"] = price
    save(out.round(4), f"{tag}_signals.csv")
    save(r.equity_curve.round(6), f"{tag}_equity.csv")

    print(f"\n{'='*78}\n[{cfg.name}]  {sc.index[0].date()} ~ {sc.index[-1].date()}\n{'='*78}")
    cmp_df = pd.DataFrame({"Flow Radar 전략": fmt(r.stats),
                           "Buy & Hold": fmt(r.bench_stats)})
    print(cmp_df.to_string())

    # 레짐 분포 & 레짐별 다음날 수익률 (신호 자체의 유효성)
    nxt = price.pct_change().shift(-1)
    reg_stat = pd.DataFrame({
        "일수": regime.value_counts().sort_index(),
        "비중(%)": (regime.value_counts(normalize=True).sort_index() * 100).round(1),
        "다음날평균수익(bp)": (nxt.groupby(regime).mean() * 10000).round(2),
        "연율화(%)": (nxt.groupby(regime).mean() * 252 * 100).round(2),
        "다음날변동성(연율%)": (nxt.groupby(regime).std() * np.sqrt(252) * 100).round(1),
    })
    reg_stat.index = [REGIME_LABELS[int(i)] for i in reg_stat.index]
    print("\n[레짐별 실제 결과 - 신호가 실제로 미래를 구분하는가]")
    print(reg_stat.to_string())

    return {"tag": tag, "cfg": cfg, "sc": sc, "price": price,
            "result": r, "regime_stat": reg_stat}


def sensitivity(panel: pd.DataFrame, raw_panel: pd.DataFrame, cfg, tag: str) -> pd.DataFrame:
    """파라미터를 흔들어도 결론이 유지되는가."""
    sc, price = prep(panel, raw_panel, cfg)
    rows = []
    for hi in (0.0, 0.10, 0.20, 0.30, 0.40):
        for cost in (5.0, 10.0, 25.0):
            for freq in ("M", "W"):
                w = to_weight(to_regime(sc["FLOW_SCORE"], hi, -hi), W_ON, W_MID, W_OFF)
                r = backtest(price, w, freq=freq, cost_bp=cost, cash_yield=CASH_YIELD)
                rows.append({
                    "시장": tag, "임계값": hi, "비용(bp)": cost, "리밸런싱": freq,
                    "CAGR(%)": round(r.stats["CAGR"] * 100, 2),
                    "변동성(%)": round(r.stats["변동성"] * 100, 2),
                    "샤프": r.stats["샤프"],
                    "MDD(%)": round(r.stats["MDD"] * 100, 2),
                    "회전율": r.stats["연회전율(편도)"],
                })
    return pd.DataFrame(rows)


def walk_forward(panel: pd.DataFrame, raw_panel: pd.DataFrame, cfg, tag: str, n_split: int = 3) -> pd.DataFrame:
    """구간을 나눠 성과가 특정 기간에만 몰려 있는지 확인."""
    sc, price = prep(panel, raw_panel, cfg)
    regime = to_regime(sc["FLOW_SCORE"], HI, LO)
    weight = to_weight(regime, W_ON, W_MID, W_OFF)
    r = backtest(price, weight, freq=FREQ, cost_bp=COST_BP, cash_yield=CASH_YIELD)
    ec = r.equity_curve

    bounds = np.array_split(np.arange(len(ec)), n_split)
    rows = []
    for i, ix in enumerate(bounds, 1):
        seg = ec.iloc[ix]
        s = perf_stats(seg["strategy_ret"])
        b = perf_stats(seg["bench_ret"])
        rows.append({
            "시장": tag, "구간": f"{i}/{n_split}",
            "기간": f"{seg.index[0].date()}~{seg.index[-1].date()}",
            "전략 CAGR(%)": round(s["CAGR"] * 100, 2),
            "B&H CAGR(%)": round(b["CAGR"] * 100, 2),
            "초과(%p)": round((s["CAGR"] - b["CAGR"]) * 100, 2),
            "전략 MDD(%)": round(s["MDD"] * 100, 2),
            "B&H MDD(%)": round(b["MDD"] * 100, 2),
            "전략 샤프": s["샤프"], "B&H 샤프": b["샤프"],
        })
    return pd.DataFrame(rows)


def layer_contribution(panel: pd.DataFrame, raw_panel: pd.DataFrame, cfg, tag: str) -> pd.DataFrame:
    """각 층을 단독으로 썼을 때의 성과 (층별 기여도 분해)."""
    sc, price = prep(panel, raw_panel, cfg)
    rows = []
    for layer in LAYERS + ["FLOW_SCORE"]:
        w = to_weight(to_regime(sc[layer], HI, LO), W_ON, W_MID, W_OFF)
        r = backtest(price, w, freq=FREQ, cost_bp=COST_BP, cash_yield=CASH_YIELD)
        rows.append({
            "시장": tag, "층": layer,
            "CAGR(%)": round(r.stats["CAGR"] * 100, 2),
            "샤프": r.stats["샤프"],
            "MDD(%)": round(r.stats["MDD"] * 100, 2),
            "회전율": r.stats["연회전율(편도)"],
        })
    b = perf_stats(price.pct_change().fillna(0.0))
    rows.append({"시장": tag, "층": "Buy&Hold",
                 "CAGR(%)": round(b["CAGR"] * 100, 2), "샤프": b["샤프"],
                 "MDD(%)": round(b["MDD"] * 100, 2), "회전율": 0.0})
    return pd.DataFrame(rows)


def main() -> int:
    print("데이터 로딩...")
    panel, raw_panel = load_panel()
    print(f"패널: {panel.index.min().date()} ~ {panel.index.max().date()}, "
          f"{panel.shape[1]}개 시계열\n")

    runs = []
    for cfg, tag in ((KOSPI_CFG, "KOSPI"), (SP500_CFG, "SP500")):
        runs.append(run_market(panel, raw_panel, cfg, tag))

    # 요약
    summary = []
    for r in runs:
        summary.append({"시장": r["cfg"].name, "전략": "Flow Radar", **fmt(r["result"].stats)})
        summary.append({"시장": r["cfg"].name, "전략": "Buy & Hold", **fmt(r["result"].bench_stats)})
    sm = pd.DataFrame(summary).set_index(["시장", "전략"])
    save(sm, "summary.csv")

    sens = pd.concat([sensitivity(panel, raw_panel, c, t) for c, t in
                      ((KOSPI_CFG, "KOSPI"), (SP500_CFG, "SP500"))], ignore_index=True)
    save(sens.set_index(["시장", "임계값", "비용(bp)", "리밸런싱"]), "sensitivity.csv")

    wf = pd.concat([walk_forward(panel, raw_panel, c, t) for c, t in
                    ((KOSPI_CFG, "KOSPI"), (SP500_CFG, "SP500"))], ignore_index=True)
    save(wf.set_index(["시장", "구간"]), "walkforward.csv")

    lc = pd.concat([layer_contribution(panel, raw_panel, c, t) for c, t in
                    ((KOSPI_CFG, "KOSPI"), (SP500_CFG, "SP500"))], ignore_index=True)
    save(lc.set_index(["시장", "층"]), "layer_contribution.csv")

    rs = pd.concat([r["regime_stat"].assign(시장=r["tag"]) for r in runs])
    save(rs, "regime_stats.csv")

    print(f"\n\n{'#'*78}\n민감도 (임계값 x 비용 x 리밸런싱)\n{'#'*78}")
    piv = sens.pivot_table(index=["시장", "임계값"], columns=["리밸런싱", "비용(bp)"],
                           values="샤프")
    print(piv.round(2).to_string())

    print(f"\n{'#'*78}\n워크포워드 (구간 3분할)\n{'#'*78}")
    print(wf.to_string(index=False))

    print(f"\n{'#'*78}\n층별 단독 성과 (기여도 분해)\n{'#'*78}")
    print(lc.to_string(index=False))

    print(f"\n결과 저장 완료 -> {RES}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
