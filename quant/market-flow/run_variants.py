# -*- coding: utf-8 -*-
"""
Flow Radar - 신호 유효성(IC) 검증 및 변형 규칙 비교

run_backtest.py 의 기본 규칙(3단계 x 월말)이 벤치마크를 못 이긴 원인을
진단하고, 진단에 근거한 대안 규칙을 '사전에 정의해' 함께 검증한다.

1) 정보계수(IC)
   거래규칙과 무관하게 Flow Score 자체가 미래 수익을 설명하는지 본다.
   IC = corr(Flow Score(t), 미래 n일 수익(t+1 ~ t+n)) - 스피어만 순위상관.
   IC > 0.03 이면 실무적으로 쓸 만한 신호로 본다.

2) 변형 규칙 (모두 사전 정의, 성과를 보고 고른 것이 아니다)
   V0 3단계 x 월말      : 기본
   V1 3단계 x 주말      : 신호는 일간인데 월 1회만 반영하면 정보가 상한다
   V2 연속형 x 주말      : w = clip(0.5 + score, 0, 1). 이산화 손실 제거
   V3 연속형+변동성타겟   : w 를 목표변동성 10%에 맞춰 재조정
                          (신호가 방향이 아니라 변동성을 예측할 때의 정석)

3) 현금수익률 0% / 2% 두 가지로 병기.
   전략은 관측일의 20~31%를 현금으로 보내므로 이 가정이 성과를 크게 좌우한다.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from flow_radar import (
    KOSPI_CFG, SP500_CFG, LAYERS, backtest, load_panel, to_regime, to_weight,
)
from run_backtest import RES, prep, save, HI, LO, COST_BP

HORIZONS = [1, 5, 20, 60]
TARGET_VOL = 0.10
VOL_WIN = 60


def information_coefficient(sc: pd.DataFrame, price: pd.Series) -> pd.DataFrame:
    """Flow Score 및 각 층의 미래수익 예측력(순위상관)."""
    rows = []
    for col in LAYERS + ["FLOW_SCORE"]:
        row = {"지표": col}
        for h in HORIZONS:
            fwd = price.shift(-h) / price - 1.0
            row[f"IC_{h}일"] = round(float(sc[col].corr(fwd, method="spearman")), 4)
        rows.append(row)
    return pd.DataFrame(rows)


def continuous_weight(score: pd.Series) -> pd.Series:
    """Flow Score 를 0~1 비중으로 선형 매핑. 0시그마 = 50%."""
    return (0.5 + score).clip(0.0, 1.0)


def vol_targeted(weight: pd.Series, price: pd.Series,
                 target: float = TARGET_VOL) -> pd.Series:
    """목표변동성 스케일링. 과거 60일 변동성만 사용(미래참조 없음)."""
    rv = price.pct_change().rolling(VOL_WIN).std() * np.sqrt(252)
    scale = (target / rv.replace(0.0, np.nan)).clip(upper=1.5)
    return (weight * scale).clip(0.0, 1.0)


def variants(sc: pd.DataFrame, price: pd.Series) -> dict[str, tuple]:
    score = sc["FLOW_SCORE"]
    w3 = to_weight(to_regime(score, HI, LO))
    wc = continuous_weight(score)
    return {
        "V0 3단계x월말": (w3, "M"),
        "V1 3단계x주말": (w3, "W"),
        "V2 연속형x주말": (wc, "W"),
        "V3 연속형+변동성타겟x주말": (vol_targeted(wc, price), "W"),
    }


def main() -> int:
    panel, raw_panel = load_panel()

    ic_all, var_all = [], []
    for cfg, tag in ((KOSPI_CFG, "KOSPI"), (SP500_CFG, "SP500")):
        sc, price = prep(panel, raw_panel, cfg)

        ic = information_coefficient(sc, price)
        ic.insert(0, "시장", tag)
        ic_all.append(ic)

        for name, (w, freq) in variants(sc, price).items():
            for cash in (0.0, 0.02):
                r = backtest(price, w, freq=freq, cost_bp=COST_BP, cash_yield=cash)
                var_all.append({
                    "시장": tag, "규칙": name, "현금이자": f"{cash*100:.0f}%",
                    "CAGR(%)": round(r.stats["CAGR"] * 100, 2),
                    "변동성(%)": round(r.stats["변동성"] * 100, 2),
                    "샤프": r.stats["샤프"],
                    "MDD(%)": round(r.stats["MDD"] * 100, 2),
                    "칼마": r.stats["칼마(CAGR/|MDD|)"],
                    "평균비중(%)": round(float(r.equity_curve["weight"].mean()) * 100, 1),
                    "회전율": r.stats["연회전율(편도)"],
                })
        b = backtest(price, pd.Series(1.0, index=price.index), freq="M",
                     cost_bp=0.0).bench_stats
        var_all.append({
            "시장": tag, "규칙": "Buy & Hold", "현금이자": "-",
            "CAGR(%)": round(b["CAGR"] * 100, 2),
            "변동성(%)": round(b["변동성"] * 100, 2),
            "샤프": b["샤프"], "MDD(%)": round(b["MDD"] * 100, 2),
            "칼마": b["칼마(CAGR/|MDD|)"], "평균비중(%)": 100.0, "회전율": 0.0,
        })

    ic_df = pd.concat(ic_all, ignore_index=True)
    var_df = pd.DataFrame(var_all)
    save(ic_df.set_index(["시장", "지표"]), "information_coefficient.csv")
    save(var_df.set_index(["시장", "규칙", "현금이자"]), "variants.csv")

    print("#" * 78)
    print("정보계수 IC - 거래규칙과 무관한 신호 자체의 예측력 (스피어만 순위상관)")
    print("#" * 78)
    print(ic_df.to_string(index=False))

    print("\n" + "#" * 78)
    print("변형 규칙 비교")
    print("#" * 78)
    for tag in ("KOSPI", "SP500"):
        print(f"\n--- {tag}")
        print(var_df[var_df["시장"] == tag].drop(columns=["시장"]).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
