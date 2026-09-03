# -*- coding: utf-8 -*-
"""
Flow Radar - 4층 자금흐름 판단 엔진

설계 원칙
---------
1. "자금 흐름"은 직접 관측할 수 없다. 관측 가능한 흔적(가격·변동성·환율·금리)의
   조합으로 추정한다. 그래서 단일 지표가 아니라 4개 층으로 나눈다.

   L1 TREND (추세)  : 돈이 이미 어디에 가 있는가        - 가격 모멘텀
   L2 RISK  (위험선호): 위험을 감수할 분위기인가          - VIX, 주식/채권 상대강도
   L3 FLOW  (자금방향): 국경을 넘는 돈이 들어오나 나가나  - 환율(원화·달러), 주식/금
   L4 COST  (자금비용): 돈값이 싸지나 비싸지나            - 국채 모멘텀, 금리 급등 충격

2. 모든 지표는 "시그마 단위"로 표준화한 뒤에야 더한다.
   - 모멘텀형 : 변동성 정규화 (n일 수익률 / 일간변동성 x sqrt(n))
   - 레벨형   : 확장 윈도 z-score
   둘 다 t시점까지의 데이터만 쓰므로 미래참조(look-ahead)가 구조적으로 불가능하다.

3. 층 점수 = 소속 지표의 평균, 최종 Flow Score = 층 점수의 가중합.
   가중치는 최적화하지 않고 경제적 논리로 사전에 고정한다(과최적화 방지).

4. 신호는 t일 종가로 계산하고 포지션은 t+1일부터 적용한다(체결 지연 1일).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

TRADING_DAYS = 252

# ----------------------------------------------------------------------------
# 데이터 로딩
# ----------------------------------------------------------------------------


def load_panel() -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    fetch_data.py 캐시를 일간 패널로 합친다.

    반환
      panel : 휴장일을 직전값으로 채운 패널 (지표 계산용)
      raw   : 채우지 않은 원계열 (각 시장의 '진짜 거래일' 판별용)

    각국 휴일이 달라 단순 합집합을 쓰면 연 306영업일 같은 값이 나오고
    연율화가 통째로 틀어진다. 그래서 두 벌을 따로 들고 간다.
    """
    fut = pd.read_csv(os.path.join(DATA, "futures_daily.csv"), index_col=0,
                      parse_dates=True, encoding="utf-8-sig")
    fx = pd.read_csv(os.path.join(DATA, "fx_daily.csv"), index_col=0,
                     parse_dates=True, encoding="utf-8-sig")
    vix = pd.read_csv(os.path.join(DATA, "vix_daily.csv"), index_col=0,
                      parse_dates=True, encoding="utf-8-sig")

    raw = fut.join(fx, how="outer").join(vix, how="outer").sort_index()
    raw = raw.where(raw > 0)          # 0/음수 호가는 결측 처리 (log 계산 보호)
    # 미래 값은 절대 끌어오지 않으므로 ffill 만 사용한다.
    panel = raw.ffill()
    return panel, raw


# ----------------------------------------------------------------------------
# 지표 정의
# ----------------------------------------------------------------------------


def logret(s: pd.Series, n: int) -> pd.Series:
    """n영업일 로그수익률."""
    return np.log(s) - np.log(s.shift(n))


def norm_mom(s: pd.Series, n: int, vol_win: int = 60) -> pd.Series:
    """
    변동성 정규화 모멘텀 (risk-adjusted momentum).

    n일 로그수익률을 같은 구간의 기대 표준편차(일간변동성 x sqrt(n))로 나눈다.
    - 자산·기간이 달라도 같은 '시그마' 단위가 되어 그대로 합산할 수 있다.
    - 60일 변동성만 있으면 계산되므로, 표본이 짧은 시장(KOSPI 선물 2014~)에서도
      긴 캘리브레이션 기간을 낭비하지 않는다. 이것이 z-score 대비 핵심 장점.
    """
    r = np.log(s).diff()
    scale = r.rolling(vol_win).std() * np.sqrt(n)
    return ((np.log(s) - np.log(s.shift(n))) / scale.replace(0.0, np.nan)).clip(-3, 3)


def ratio_mom(a: pd.Series, b: pd.Series, n: int) -> pd.Series:
    """a/b 상대강도의 변동성 정규화 모멘텀. 양수면 a(위험자산) 우위."""
    return norm_mom(a / b, n)


def expanding_z(s: pd.Series, min_periods: int = 252, clip: float = 3.0) -> pd.Series:
    """확장 윈도 z-score. t시점까지의 정보만 사용한다(레벨형 지표 전용)."""
    mu = s.expanding(min_periods=min_periods).mean()
    sd = s.expanding(min_periods=min_periods).std()
    return ((s - mu) / sd.replace(0.0, np.nan)).clip(-clip, clip)


@dataclass
class MarketConfig:
    """시장별 설정. 지표 구성은 동일하고 입력 컬럼만 바뀐다."""
    name: str
    equity: str                 # 대상 위험자산 (선물 연결가격 컬럼)
    bond: str                   # 해당국 국채선물
    fx_local: str | None        # 자국통화 (USDKRW). 미국은 None
    start: str
    end: str
    layer_weights: Dict[str, float] = field(default_factory=lambda: {
        "TREND": 0.35, "RISK": 0.25, "FLOW": 0.25, "COST": 0.15,
    })


def build_signals(panel: pd.DataFrame, cfg: MarketConfig) -> pd.DataFrame:
    """
    원시 지표를 만든다. 부호는 전부 '클수록 위험선호 / 자금유입' 으로 통일한다.
    전체 가용 기간에 대해 계산하고, 구간 절단은 백테스트 단계에서 한다.
    """
    p = panel
    eq, bd = p[cfg.equity], p[cfg.bond]
    vix, gold, dxy = p["VIX_SPOT"], p["GOLD"], p["DXY"]

    sig: Dict[str, pd.Series] = {}

    # ---- L1 TREND : 돈이 이미 어디 가 있는가 -------------------------------
    sig["TREND.mom_1m"] = norm_mom(eq, 21)
    sig["TREND.mom_3m"] = norm_mom(eq, 63)
    sig["TREND.mom_12m"] = norm_mom(eq, 252)

    # ---- L2 RISK : 위험을 감수할 분위기인가 --------------------------------
    #  VIX 는 '레벨' 자체에 정보가 있으므로 확장 z 사용 (1990년부터 데이터 존재)
    sig["RISK.vix_level"] = expanding_z(-np.log(vix))
    sig["RISK.vix_change"] = -norm_mom(vix, 20)
    sig["RISK.eq_vs_bond"] = ratio_mom(eq, bd, 60)

    # ---- L3 FLOW : 국경을 넘는 돈의 방향 -----------------------------------
    sig["FLOW.usd_weak"] = -norm_mom(dxy, 60)        # 달러 약세 = 위험자산·신흥국 유입
    sig["FLOW.eq_vs_gold"] = ratio_mom(eq, gold, 60)  # 주식 > 금 = 위험선호
    if cfg.fx_local:
        # 원화 강세 = 외국인 자금 유입의 가장 빠른 흔적
        sig["FLOW.krw_strong"] = -norm_mom(p[cfg.fx_local], 60)

    # ---- L4 COST : 돈값이 싸지나 비싸지나 ----------------------------------
    sig["COST.bond_mom"] = norm_mom(bd, 120)          # 국채가격 상승 = 금리 하락 = 완화
    #  금리 급등(국채 급락) 충격만 벌점으로. 평시에는 0 부근.
    sig["COST.rate_shock"] = -np.maximum(0.0, -norm_mom(bd, 20))

    return pd.DataFrame(sig)


LAYERS = ["TREND", "RISK", "FLOW", "COST"]


def score_frame(raw: pd.DataFrame, cfg: MarketConfig) -> pd.DataFrame:
    """지표 → 층 점수 → Flow Score (모두 시그마 단위)."""
    layers = {}
    for layer in LAYERS:
        cols = [c for c in raw.columns if c.startswith(layer + ".")]
        layers[layer] = raw[cols].mean(axis=1)
    L = pd.DataFrame(layers)

    w = cfg.layer_weights
    total_w = sum(w[k] for k in LAYERS)
    L["FLOW_SCORE"] = sum(L[k] * w[k] for k in LAYERS) / total_w

    return pd.concat([raw, L], axis=1)


# ----------------------------------------------------------------------------
# 레짐 판정 & 배분
# ----------------------------------------------------------------------------

REGIME_LABELS = {2: "확장(Risk-On)", 1: "중립(Neutral)", 0: "수축(Risk-Off)"}


def to_regime(score: pd.Series, hi: float = 0.20, lo: float = -0.20) -> pd.Series:
    r = pd.Series(1, index=score.index, dtype="int64")
    r[score > hi] = 2
    r[score < lo] = 0
    r[score.isna()] = np.nan
    return r


def to_weight(regime: pd.Series, w_on: float = 1.0, w_mid: float = 0.5,
              w_off: float = 0.0) -> pd.Series:
    return regime.map({2: w_on, 1: w_mid, 0: w_off})


# ----------------------------------------------------------------------------
# 백테스트 엔진
# ----------------------------------------------------------------------------


@dataclass
class BacktestResult:
    equity_curve: pd.DataFrame
    stats: Dict[str, float]
    bench_stats: Dict[str, float]


def rebalance_mask(idx: pd.DatetimeIndex, freq: str) -> pd.Series:
    """리밸런싱 시점(해당 기간의 마지막 영업일)에 True."""
    if freq == "D":
        return pd.Series(True, index=idx)
    grp = idx.to_period({"M": "M", "W": "W", "Q": "Q"}[freq])
    s = pd.Series(idx, index=idx)
    last = s.groupby(grp).transform("max")
    return pd.Series(idx == last, index=idx)


def backtest(price: pd.Series, target_w: pd.Series, freq: str = "M",
             cost_bp: float = 10.0, cash_yield: float = 0.0,
             lag: int = 1) -> BacktestResult:
    """
    price     : 대상자산 일간 종가 (선물 연결가격)
    target_w  : 신호로 산출된 목표 비중 (0~1), price 와 같은 인덱스
    freq      : 리밸런싱 주기 ('M' 월말, 'W' 주말, 'D' 매일)
    cost_bp   : 편도 거래비용(bp). 비중 변화량에 비례해 차감
    cash_yield: 현금 부분 연이율 (보수적으로 0 권장)
    lag       : 신호 계산일 이후 몇 영업일 뒤 체결하는가
    """
    df = pd.DataFrame({"price": price, "target": target_w}).dropna()
    ret = df["price"].pct_change().fillna(0.0)

    # 리밸런싱일에만 목표비중을 갱신하고, lag 일 뒤부터 실제 적용
    reb = rebalance_mask(df.index, freq)
    held = df["target"].where(reb).ffill()
    held = held.shift(lag).fillna(0.0)

    turnover = held.diff().abs().fillna(held.abs())
    cost = turnover * (cost_bp / 10000.0)

    daily_cash = (1.0 + cash_yield) ** (1.0 / TRADING_DAYS) - 1.0
    strat_ret = held * ret + (1.0 - held) * daily_cash - cost

    curve = pd.DataFrame({
        "price": df["price"],
        "weight": held,
        "strategy_ret": strat_ret,
        "bench_ret": ret,
    })
    curve["strategy"] = (1.0 + curve["strategy_ret"]).cumprod()
    curve["benchmark"] = (1.0 + curve["bench_ret"]).cumprod()

    return BacktestResult(
        equity_curve=curve,
        stats=perf_stats(curve["strategy_ret"], turnover),
        bench_stats=perf_stats(curve["bench_ret"]),
    )


def perf_stats(ret: pd.Series, turnover: pd.Series | None = None) -> Dict[str, float]:
    ret = ret.dropna()
    if ret.empty:
        return {}
    # 연율화는 '실제 달력 기간' 기준. 관측 빈도는 데이터에서 추정한다.
    span_days = (ret.index[-1] - ret.index[0]).days
    n_years = max(span_days / 365.25, 1e-9)
    ann = len(ret) / n_years
    cum = float((1.0 + ret).prod())
    cagr = cum ** (1.0 / n_years) - 1.0
    vol = float(ret.std() * np.sqrt(ann))
    sharpe = cagr / vol if vol > 0 else np.nan

    curve = (1.0 + ret).cumprod()
    mdd = float((curve / curve.cummax() - 1.0).min())

    downside = ret[ret < 0]
    dvol = float(downside.std() * np.sqrt(ann)) if len(downside) > 1 else np.nan
    sortino = cagr / dvol if dvol and dvol > 0 else np.nan

    monthly = (1.0 + ret).resample("ME").prod() - 1.0

    out = {
        "누적수익(배)": round(cum, 3),
        "CAGR": round(cagr, 4),
        "변동성": round(vol, 4),
        "샤프": round(sharpe, 3),
        "소르티노": round(sortino, 3) if sortino == sortino else np.nan,
        "MDD": round(mdd, 4),
        "칼마(CAGR/|MDD|)": round(cagr / abs(mdd), 3) if mdd < 0 else np.nan,
        "월간승률": round(float((monthly > 0).mean()), 3),
        "관측연수": round(n_years, 1),
    }
    if turnover is not None:
        out["연회전율(편도)"] = round(float(turnover.sum() / n_years), 2)
    return out


# ----------------------------------------------------------------------------
# 시장 프리셋
# ----------------------------------------------------------------------------

KOSPI_CFG = MarketConfig(
    name="한국 (KOSPI200 선물)",
    equity="KOSPI", bond="KR10", fx_local="USDKRW",
    start="2014-03-13", end="2024-03-29",
)

SP500_CFG = MarketConfig(
    name="미국 (S&P500 선물)",
    equity="SP500", bond="US10", fx_local=None,
    start="1990-01-02", end="2024-03-28",
)
