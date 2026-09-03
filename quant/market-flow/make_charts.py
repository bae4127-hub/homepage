# -*- coding: utf-8 -*-
"""
결과 차트 생성. (컨테이너에 한글 폰트가 없으므로 라벨은 영문으로 쓴다)
  - {시장}_curve.png : 누적곡선 + 보유비중
  - {시장}_score.png : Flow Score 와 레짐 구간
"""
from __future__ import annotations

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")

TITLES = {"KOSPI": "Korea (KOSPI200 futures)", "SP500": "US (S&P500 futures)"}


def curve_chart(tag: str) -> None:
    ec = pd.read_csv(os.path.join(RES, f"{tag}_equity.csv"), index_col=0,
                     parse_dates=True, encoding="utf-8-sig")
    fig, ax = plt.subplots(2, 1, figsize=(11, 7), height_ratios=[3, 1], sharex=True)

    ax[0].plot(ec.index, ec["strategy"], lw=1.6, color="#1f4e79", label="Flow Radar (V0: 3-state x monthly)")
    ax[0].plot(ec.index, ec["benchmark"], lw=1.2, color="#c00000", alpha=.75, label="Buy & Hold")
    ax[0].set_yscale("log")
    ax[0].set_ylabel("Growth of 1 (log)")
    ax[0].set_title(f"Flow Radar backtest - {TITLES[tag]}", fontsize=13, weight="bold")
    ax[0].legend(loc="upper left", fontsize=9)
    ax[0].grid(alpha=.25)

    ax[1].fill_between(ec.index, 0, ec["weight"], color="#2e75b6", alpha=.55, step="post")
    ax[1].set_ylabel("Equity weight")
    ax[1].set_ylim(0, 1.05)
    ax[1].grid(alpha=.25)

    fig.tight_layout()
    fig.savefig(os.path.join(RES, f"{tag}_curve.png"), dpi=130)
    plt.close(fig)


def score_chart(tag: str) -> None:
    sg = pd.read_csv(os.path.join(RES, f"{tag}_signals.csv"), index_col=0,
                     parse_dates=True, encoding="utf-8-sig")
    fig, ax = plt.subplots(2, 1, figsize=(11, 7), height_ratios=[2, 2], sharex=True)

    ax[0].plot(sg.index, sg["종가"], lw=1.1, color="#333")
    on = sg["FLOW_SCORE"] > 0.20
    off = sg["FLOW_SCORE"] < -0.20
    ax[0].fill_between(sg.index, sg["종가"].min(), sg["종가"].max(), where=on,
                       color="#2e9e4f", alpha=.13, label="Risk-On")
    ax[0].fill_between(sg.index, sg["종가"].min(), sg["종가"].max(), where=off,
                       color="#c00000", alpha=.13, label="Risk-Off")
    ax[0].set_ylabel("Index (continuous futures)")
    ax[0].set_title(f"Flow Score regimes - {TITLES[tag]}", fontsize=13, weight="bold")
    ax[0].legend(loc="upper left", fontsize=9)
    ax[0].grid(alpha=.25)

    for c, col in zip(["TREND", "RISK", "FLOW", "COST"],
                      ["#1f4e79", "#c00000", "#2e9e4f", "#bf8f00"]):
        ax[1].plot(sg.index, sg[c].rolling(20).mean(), lw=1.0, alpha=.75, label=c)
    ax[1].plot(sg.index, sg["FLOW_SCORE"], lw=1.8, color="black", label="FLOW SCORE")
    ax[1].axhline(0.20, ls="--", lw=.8, color="#2e9e4f")
    ax[1].axhline(-0.20, ls="--", lw=.8, color="#c00000")
    ax[1].set_ylabel("Sigma")
    ax[1].legend(ncol=5, fontsize=8, loc="lower left")
    ax[1].grid(alpha=.25)

    fig.tight_layout()
    fig.savefig(os.path.join(RES, f"{tag}_score.png"), dpi=130)
    plt.close(fig)


def extended_chart() -> None:
    """27.5년 한국 곡선 (정적 가중 x 주말) - 위기 구간 표시."""
    ec = pd.read_csv(os.path.join(RES, "extended_curve_static.csv"), index_col=0,
                     parse_dates=True, encoding="utf-8-sig")
    fig, ax = plt.subplots(2, 1, figsize=(12, 7.5), height_ratios=[3, 1], sharex=True)
    for a, b, lab in [("2000-01-01", "2001-09-30", "Dot-com"),
                      ("2007-11-01", "2009-03-31", "GFC"),
                      ("2020-02-01", "2020-03-31", "Covid"),
                      ("2022-01-01", "2022-10-31", "Tightening")]:
        ax[0].axvspan(pd.Timestamp(a), pd.Timestamp(b), color="#B4551F", alpha=.10)
        ax[0].text(pd.Timestamp(a), 0.02, lab, fontsize=8, color="#8a4318",
                   rotation=90, va="bottom", transform=ax[0].get_xaxis_transform())
    ax[0].plot(ec.index, ec["strategy"], lw=1.7, color="#00786C", label="Flow Radar (static x weekly)")
    ax[0].plot(ec.index, ec["benchmark"], lw=1.2, color="#B4551F", alpha=.8, label="Buy & Hold")
    ax[0].set_yscale("log"); ax[0].set_ylabel("Growth of 1 (log)")
    ax[0].set_title("Korea 27.5 years (1997-07 ~ 2025-03) - parameters fixed throughout",
                    fontsize=13, weight="bold")
    ax[0].legend(loc="upper left", fontsize=9); ax[0].grid(alpha=.25)
    ax[1].fill_between(ec.index, 0, ec["weight"], color="#2e75b6", alpha=.5, step="post")
    ax[1].set_ylabel("Equity weight"); ax[1].set_ylim(0, 1.05); ax[1].grid(alpha=.25)
    fig.tight_layout(); fig.savefig(os.path.join(RES, "KOREA27Y_curve.png"), dpi=130)
    plt.close(fig)


if __name__ == "__main__":
    for tag in ("KOSPI", "SP500"):
        curve_chart(tag)
        score_chart(tag)
        print(f"{tag} 차트 저장")
    extended_chart()
    print("KOREA27Y 차트 저장")
