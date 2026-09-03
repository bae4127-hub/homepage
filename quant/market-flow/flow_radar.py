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


def _extend_tail(daily: pd.Series, monthly: pd.Series,
                 index: pd.DatetimeIndex) -> pd.Series:
    """일간 계열이 끝난 뒤를 월간 계열의 수익률로 이어 붙인다."""
    d = daily.dropna()
    if d.empty:
        return daily
    end = d.index.max()
    tail = monthly.loc[monthly.index > end]
    if tail.empty:
        return daily
    anchor = monthly.loc[monthly.index <= end]
    if anchor.empty:
        return daily
    factor = float(d.loc[end]) / float(anchor.iloc[-1])
    ext = (tail * factor).reindex(index).ffill()
    out = daily.copy()
    fill = ext.loc[ext.index > end]
    out.loc[out.index > end] = out.loc[out.index > end].fillna(fill)
    return out


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
    kl = pd.read_csv(os.path.join(DATA, "kospi_long.csv"), index_col=0,
                     parse_dates=True, encoding="utf-8-sig")[["KOSPI_LONG"]]
    mm = pd.read_csv(os.path.join(DATA, "macro_monthly.csv"), index_col=0,
                     parse_dates=True, encoding="utf-8-sig")

    raw = fut.join(fx, how="outer").join(vix, how="outer").join(kl, how="outer").sort_index()
    # 롤조정 연결선물은 레벨이 음수가 될 수 있고 그 값도 유효하다(차분이 참값).
    # 그래서 음수를 버리지 않고 '정확히 0'(결측 표기)만 제거한다.
    # 로그를 취하는 계열은 VIX 뿐이므로 거기에만 양수 조건을 건다.
    raw = raw.mask(raw == 0)
    raw["VIX_SPOT"] = raw["VIX_SPOT"].where(raw["VIX_SPOT"] > 0)

    # 금·미국채 선물은 2024-03 에서 끝난다. 그 뒤 구간은 월간 계열의 수익률로 잇는다.
    # (레벨을 직접 붙이면 현물/선물 수준차가 가짜 점프로 들어간다)
    for fut_col, m_col in (("GOLD", "GOLD_M"), ("US10", "US10_M")):
        raw[fut_col] = _extend_tail(raw[fut_col], mm[m_col], raw.index)
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

    n일 '가격 변화량'을 같은 구간의 기대 표준편차(일간 변화량의 표준편차 x sqrt(n))
    로 나눈다. 결과는 시그마 단위라 자산·기간이 달라도 그대로 합산할 수 있다.

    로그수익률이 아니라 차분을 쓰는 이유
    ------------------------------------
    롤조정(back-adjusted) 연결선물은 롤 스프레드가 누적되어 레벨이 0 근처나
    음수로 내려갈 수 있다. 실제로 미10년 국채선물 연결가격은 1990~94년에
    0.05까지 떨어져, 로그수익률로 계산하면 하루 10%가 넘는 날이 110일 나왔다.
    10년 국채가 하루에 10% 움직이는 일은 없다 - 전부 수치 인공물이다.
    롤조정 시계열은 '레벨'이 아니라 '차분'이 참값이므로 차분을 쓰는 것이 맞다.
    레벨이 안정적인 계열(지수·환율)에서는 두 방식의 정규화 결과가 사실상 같다.

    60일 변동성만 있으면 계산되므로, 표본이 짧은 시장에서도 긴 캘리브레이션
    기간을 낭비하지 않는다. 이것이 z-score 대비 핵심 장점.
    """
    d = s.diff()
    scale = d.rolling(vol_win).std() * np.sqrt(n)
    return ((s - s.shift(n)) / scale.replace(0.0, np.nan)).clip(-3, 3)


def rel_mom(a: pd.Series, b: pd.Series, n: int) -> pd.Series:
    """
    상대강도. 두 자산의 '시그마 단위 모멘텀 차'로 정의한다.

    a/b 비율을 쓰지 않는 이유: 롤조정 연결선물의 b 가 0 근처로 가면 비율이
    폭발한다. 각자 정규화한 뒤 빼면 그 문제가 사라지고, 단위도 그대로 시그마다.
    양수면 a(위험자산) 우위.
    """
    return (norm_mom(a, n) - norm_mom(b, n)).clip(-3, 3)


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
    sig["RISK.eq_vs_bond"] = rel_mom(eq, bd, 60)

    # ---- L3 FLOW : 국경을 넘는 돈의 방향 -----------------------------------
    sig["FLOW.usd_weak"] = -norm_mom(dxy, 60)        # 달러 약세 = 위험자산·신흥국 유입
    sig["FLOW.eq_vs_gold"] = rel_mom(eq, gold, 60)   # 주식 > 금 = 위험선호
    if cfg.fx_local:
        # 원화 강세 = 외국인 자금 유입의 가장 빠른 흔적
        sig["FLOW.krw_strong"] = -norm_mom(p[cfg.fx_local], 60)

    # ---- L4 COST : 돈값이 싸지나 비싸지나 ----------------------------------
    sig["COST.bond_mom"] = norm_mom(bd, 120)          # 국채가격 상승 = 금리 하락 = 완화
    #  금리 급등(국채 급락) 충격만 벌점으로. 평시에는 0 부근.
    sig["COST.rate_shock"] = -np.maximum(0.0, -norm_mom(bd, 20))

    return pd.DataFrame(sig)


LAYERS = ["TREND", "RISK", "FLOW", "COST"]


def trailing_ic(layer: pd.Series, price: pd.Series, horizon: int = 20,
                min_periods: int = 756) -> pd.Series:
    """
    t시점까지 실현된 정보만으로 계산한 층별 정보계수.

    x = horizon+1일 전의 층 점수      (그 시점에 이미 알고 있던 값)
    y = 그 이후 horizon일간 실현수익   (t시점에 이미 관측된 값)
    두 계열의 확장 윈도 상관 → t시점에 "이 층이 지금까지 맞았나"를 답한다.
    미래 정보가 들어갈 여지가 없다.
    """
    x = layer.shift(horizon + 1)
    y = price.pct_change(horizon)
    return x.expanding(min_periods=min_periods).corr(y)


def score_frame(raw: pd.DataFrame, cfg: MarketConfig,
                price: pd.Series | None = None,
                dynamic: bool = False, ic_band: float = 0.02,
                ic_horizon: int = 20) -> pd.DataFrame:
    """
    지표 → 층 점수 → Flow Score (모두 시그마 단위).

    dynamic=True 면 각 층의 부호를 '지금까지의 실적(trailing IC)'이 정한다.
      IC > +band  → 그대로       (+1)
      IC < -band  → 부호 뒤집기  (-1)
      그 사이     → 이 층은 쉰다  ( 0)
    검증 결과 RISK 층의 IC가 두 시장 모두 음(-0.10)이었는데, 그 사실을
    사람이 보고 손으로 뒤집으면 데이터 스누핑이다. 규칙이 스스로,
    과거 데이터만 보고 뒤집게 만든 것이 이 옵션이다.
    """
    layers = {}
    for layer in LAYERS:
        cols = [c for c in raw.columns if c.startswith(layer + ".")]
        layers[layer] = raw[cols].mean(axis=1)
    L = pd.DataFrame(layers)

    w = cfg.layer_weights
    if not dynamic:
        total_w = sum(w[k] for k in LAYERS)
        L["FLOW_SCORE"] = sum(L[k] * w[k] for k in LAYERS) / total_w
        return pd.concat([raw, L], axis=1)

    if price is None:
        raise ValueError("dynamic=True 에는 price 가 필요하다")

    num = pd.Series(0.0, index=L.index)
    den = pd.Series(0.0, index=L.index)
    for layer in LAYERS:
        ic = trailing_ic(L[layer], price, horizon=ic_horizon)
        sgn = pd.Series(0.0, index=L.index)
        sgn[ic > ic_band] = 1.0
        sgn[ic < -ic_band] = -1.0
        sgn[ic.isna()] = 1.0          # IC 표본이 모이기 전에는 사전 가중치 그대로
        L[f"SGN.{layer}"] = sgn
        num += L[layer] * w[layer] * sgn
        den += w[layer] * sgn.abs()
    L["FLOW_SCORE"] = num / den.replace(0.0, np.nan)

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

# 장기 검증용. KOSPI200 선물이 2014년부터라 현물지수로 앞뒤를 이어 27년으로 늘렸다.
# 한국 국채선물(KR10)도 2014년부터뿐이라, 이 설정에서는 자금비용 층에
# 미국채(US10)를 쓴다 - 한국은 글로벌 금리가 자금비용을 정하는 시장이라는 관점.
KOSPI_LONG_CFG = MarketConfig(
    name="한국 장기 (KOSPI 현물⊕선물)",
    equity="KOSPI_LONG", bond="US10", fx_local="USDKRW",
    start="1997-07-01", end="2025-03-20",
)

# 위 설정의 국채 대체가 결과를 바꾸는지 확인하는 대조군 (2014~2024 구간 한정)
KOSPI_US10_CFG = MarketConfig(
    name="한국 2014-24 (국채만 US10로 교체)",
    equity="KOSPI", bond="US10", fx_local="USDKRW",
    start="2014-03-13", end="2024-03-29",
)

SP500_CFG = MarketConfig(
    name="미국 (S&P500 선물)",
    equity="SP500", bond="US10", fx_local=None,
    start="1990-01-02", end="2024-03-28",
)
