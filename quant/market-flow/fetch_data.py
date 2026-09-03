# -*- coding: utf-8 -*-
"""
Flow Radar - 데이터 수집 레이어

원격(에이전트) 환경에서 접근 가능한 공개 원본에서 교차자산 시계열을 받아
data/ 폴더에 캐시한다. 모든 CSV는 UTF-8(BOM)로 저장한다.

출처
----
1) pysystemtrade (pst-group/pysystemtrade)
   선물 연결가격(롤조정). KOSPI200/S&P500/VIX/미10년/한10년/금/원유 등.
2) datasets/exchange-rates  : 미 연준 H.10 일간 환율 (USD/KRW 포함, 1971~)
3) datasets/finance-vix     : CBOE VIX 현물 일간 (1990~)
3b) KOSPI 현물지수(KS11) 장기 시계열 - 아래 KS11_SOURCES 참고
4) datasets/s-and-p-500     : Shiller S&P500 월간 (1871~, 배당·CPI·PE10)

국내 실전 운용에서는 adapters_kr.py 의 KIS/pykrx 어댑터로 교체한다.
"""
from __future__ import annotations

import io
import os
import sys
import urllib.request

import numpy as np

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)

PST = "https://raw.githubusercontent.com/pst-group/pysystemtrade/master/data/futures/adjusted_prices_csv"
DH = "https://raw.githubusercontent.com/datasets"

FUTURES = ["KOSPI", "SP500", "VIX", "US10", "KR10", "GOLD", "CRUDE_W", "NIKKEI", "EUROSTX"]

# KOSPI 현물지수(KS11). 선물 연결가격이 2014-03 ~ 2024-03 뿐이라 앞뒤를 현물로 잇는다.
#  - old : 1997-07 ~ 2014-03  (2008년 금융위기 포함)
#  - new : 2024-03 ~ 2025-03  (선물 데이터 종료 이후 = 순수 전진 OOS 구간)
#  - xchk: 2006-10 ~ 2022-06  (교차검증용. old 와 1832일 겹치며 오차 0.000%)
KS11_SOURCES = {
    "old": "https://raw.githubusercontent.com/SkivHisink/EconometricNSU/master/"
           "Task13/StockIndices/StockIndices/Korea_KS11.csv",
    "new": "https://raw.githubusercontent.com/johngreenough/volatility/master/"
           "historical_data/KS11.csv",
    "xchk": "https://raw.githubusercontent.com/bumhoson/SpilloverVolPrediction/main/"
            "global%20index%20etf%20return/KS11.csv",
}

# datasets/exchange-rates 는 연준 H.10 을 "1달러당 통화단위" 로 통일해 제공한다.
# (2007년말 Euro 0.68, GBP 0.50 → 유로/파운드도 units-per-USD 표기. 부호 반전 불필요)

# 달러지수(DXY) 바스켓 가중치
DXY_WEIGHTS = {
    "Euro": 0.576,
    "Japan": 0.136,
    "United Kingdom": 0.119,
    "Canada": 0.091,
    "Sweden": 0.042,
    "Switzerland": 0.036,
}


def _get(url: str, timeout: int = 90) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "flow-radar/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _save(df: pd.DataFrame, name: str) -> str:
    path = os.path.join(DATA, name)
    df.to_csv(path, encoding="utf-8-sig")
    return path


def fetch_futures() -> pd.DataFrame:
    """선물 연결가격을 일간 종가 패널로 정리."""
    cols = {}
    for sym in FUTURES:
        raw = _get(f"{PST}/{sym}.csv")
        d = pd.read_csv(io.BytesIO(raw), parse_dates=["DATETIME"]).dropna()
        # 장중 타임스탬프가 섞여 있으므로 일자별 마지막 값을 종가로 본다
        s = d.set_index("DATETIME")["price"].sort_index()
        cols[sym] = s.groupby(s.index.normalize()).last()
        print(f"  {sym:9s} {len(cols[sym]):6d}  {cols[sym].index.min().date()} ~ {cols[sym].index.max().date()}")
    panel = pd.DataFrame(cols).sort_index()
    panel.index.name = "date"
    return panel


def fetch_fx() -> pd.DataFrame:
    """연준 H.10 일간 환율 → USDKRW 원계열 + 달러지수(DXY 합성)."""
    raw = _get(f"{DH}/exchange-rates/main/data/daily.csv")
    d = pd.read_csv(io.BytesIO(raw), parse_dates=["Date"])
    d = d.rename(columns={"Exchange rate": "rate"})
    d = d[d["rate"] > 0]

    wide = d.pivot_table(index="Date", columns="Country", values="rate")

    # 각 통화의 일간 로그변화(1달러당 통화단위 기준: 오르면 달러 강세)를
    # 가중평균한 뒤 누적한다. 레벨이 아니라 변화를 합치는 이유는 유로가
    # 1999년부터만 존재하기 때문이다. 결측 통화는 그날 가중치에서 빼고
    # 재정규화하므로, 유로 이전 구간도 나머지 5통화로 지수가 이어진다.
    # (레벨을 min_count 로 묶으면 1999년 이전이 통째로 결측이 된다)
    chg, wts = [], []
    for c, w in DXY_WEIGHTS.items():
        if c not in wide.columns:
            continue
        chg.append(np.log(wide[c].astype(float)).diff().rename(c))
        wts.append(w)
    C = pd.concat(chg, axis=1)
    W = pd.Series(wts, index=C.columns)
    avail = C.notna().mul(W, axis=1).sum(axis=1)
    dxy_chg = C.mul(W, axis=1).sum(axis=1) / avail.replace(0.0, np.nan)
    dxy = 100.0 * np.exp(dxy_chg.fillna(0.0).cumsum())

    out = pd.DataFrame({"USDKRW": wide.get("South Korea"), "DXY": dxy})
    out.index.name = "date"
    return out.dropna(how="all")


def _ks11_old() -> pd.Series:
    d = pd.read_csv(io.BytesIO(_get(KS11_SOURCES["old"])), parse_dates=["Date"])
    return d.set_index("Date")["Close"].astype(float).sort_index()


def _ks11_new() -> pd.Series:
    d = pd.read_csv(io.BytesIO(_get(KS11_SOURCES["new"])))
    idx = pd.to_datetime(d["Date"], utc=True).dt.tz_localize(None).dt.normalize()
    return pd.Series(d["Close"].astype(float).values, index=idx).sort_index()


def _ks11_xchk() -> pd.Series:
    d = pd.read_csv(io.BytesIO(_get(KS11_SOURCES["xchk"])))
    d.columns = [c.strip('\ufeff"') for c in d.columns]
    idx = pd.to_datetime(d["Date"], format="%m/%d/%Y")
    px = d["Price"].astype(str).str.replace(",", "").astype(float)
    return pd.Series(px.values, index=idx).sort_index()


def fetch_kospi_long(futures: pd.DataFrame) -> pd.DataFrame:
    """
    KOSPI 장기 시계열 조립.

    현물지수(1997~2014) → KOSPI200 선물 연결가격(2014~2024) → 현물지수(2024~2025)
    를 '일간 수익률' 단위로 이어붙인다. 레벨을 직접 붙이면 현물/선물의 절대수준 차이
    (배당·베이시스)가 가짜 점프로 들어가므로, 수익률을 이어 누적하는 방식을 쓴다.

    구간 경계는 겹치는 날을 잘라 중복을 없앤다.
    """
    old, new, xchk = _ks11_old(), _ks11_new(), _ks11_xchk()

    # 교차검증: 독립 출처 두 개가 같은 값을 주는지 확인하고 어긋나면 알린다
    ov = pd.concat([old.rename("a"), xchk.rename("b")], axis=1).dropna()
    err = float((ov["a"] / ov["b"] - 1.0).abs().max()) if len(ov) else float("nan")
    print(f"  교차검증 {len(ov)}일 겹침, 최대오차 {err*100:.4f}%")

    fut = futures["KOSPI"].dropna()
    f0, f1 = fut.index.min(), fut.index.max()

    segs = [
        old.loc[: f0 - pd.Timedelta(days=1)],
        fut,
        new.loc[f1 + pd.Timedelta(days=1):],
    ]
    rets = [s.pct_change().dropna() for s in segs]
    # 구간 첫날은 직전 구간 종가와 이어지므로 수익률을 알 수 없다 → 0으로 둔다
    joined = pd.concat(rets).sort_index()
    joined = joined[~joined.index.duplicated(keep="first")]

    level = (1.0 + joined).cumprod() * float(segs[0].iloc[0])
    level = pd.concat([pd.Series([float(segs[0].iloc[0])], index=[segs[0].index[0]]),
                       level]).sort_index()

    src = pd.Series("futures", index=level.index)
    src.loc[: f0 - pd.Timedelta(days=1)] = "spot_old"
    src.loc[f1 + pd.Timedelta(days=1):] = "spot_new"

    out = pd.DataFrame({"KOSPI_LONG": level, "source": src})
    out.index.name = "date"
    for tag in ("spot_old", "futures", "spot_new"):
        seg = out[out["source"] == tag]
        print(f"  {tag:9s} {len(seg):5d}일  {seg.index.min().date()} ~ {seg.index.max().date()}")
    return out


def fetch_macro_monthly() -> pd.DataFrame:
    """
    금 현물(월간)과 미 10년 국채금리(월간).

    선물 연결가격은 2024-03 에서 끝난다. 그 이후 구간(전진 OOS)에서 금·국채
    지표가 통째로 결측이 되어 Flow Score 자체가 계산되지 않는 문제가 있었다.
    해상도는 낮지만 2026년까지 이어지는 이 두 계열로 꼬리를 잇는다.
    60~120일 모멘텀에 쓰이므로 월간 해상도로도 근사가 성립한다.

    금리는 가격이 아니므로 듀레이션 근사로 채권가격 프록시를 만든다.
      P ~ exp(-D x y),  D = 8년 (10년 국채선물의 대략적 듀레이션)
    수준이 아니라 변화율만 쓰이므로 D 의 정확도는 결과를 좌우하지 않는다.
    """
    g = pd.read_csv(io.BytesIO(_get(f"{DH}/gold-prices/main/data/monthly.csv")))
    gold = pd.Series(g["Price"].astype(float).values,
                     index=pd.to_datetime(g["Date"], format="%Y-%m")).sort_index()

    b = pd.read_csv(io.BytesIO(_get(f"{DH}/bond-yields-us-10y/main/data/monthly.csv")),
                    parse_dates=["Date"])
    y = b.set_index("Date")["Rate"].astype(float).sort_index() / 100.0
    bond_px = np.exp(-8.0 * y)

    out = pd.DataFrame({"GOLD_M": gold, "US10_M": bond_px})
    out.index.name = "date"
    return out


def fetch_vix_spot() -> pd.DataFrame:
    raw = _get(f"{DH}/finance-vix/main/data/vix-daily.csv")
    d = pd.read_csv(io.BytesIO(raw), parse_dates=["DATE"])
    out = d.set_index("DATE")[["CLOSE"]].rename(columns={"CLOSE": "VIX_SPOT"})
    out.index.name = "date"
    return out.sort_index()


def fetch_sp500_monthly() -> pd.DataFrame:
    raw = _get(f"{DH}/s-and-p-500/main/data/data.csv")
    d = pd.read_csv(io.BytesIO(raw), parse_dates=["Date"])
    d = d.set_index("Date")
    out = d[["SP500", "Dividend", "Long Interest Rate", "Consumer Price Index", "PE10"]]
    out.index.name = "date"
    return out


def main() -> int:
    print("[1/6] 선물 연결가격 (pysystemtrade)")
    fut = fetch_futures()
    _save(fut, "futures_daily.csv")

    print("[2/6] 연준 H.10 환율")
    fx = fetch_fx()
    print(f"  USDKRW {fx['USDKRW'].dropna().index.min().date()} ~ {fx['USDKRW'].dropna().index.max().date()}")
    _save(fx, "fx_daily.csv")

    print("[3/6] KOSPI 장기 시계열 (현물 ⊕ 선물 ⊕ 현물)")
    kl = fetch_kospi_long(fut)
    _save(kl, "kospi_long.csv")

    print("[4/6] 금·미10년 월간 (선물 종료 이후 꼬리 연장용)")
    mm = fetch_macro_monthly()
    print(f"  GOLD_M ~ {mm['GOLD_M'].dropna().index.max().date()}, "
          f"US10_M ~ {mm['US10_M'].dropna().index.max().date()}")
    _save(mm, "macro_monthly.csv")

    print("[5/6] VIX 현물")
    vix = fetch_vix_spot()
    _save(vix, "vix_daily.csv")

    print("[6/6] S&P500 월간 (Shiller)")
    spm = fetch_sp500_monthly()
    _save(spm, "sp500_monthly.csv")

    print("\n완료. data/ 에 6개 파일 저장")
    return 0


if __name__ == "__main__":
    sys.exit(main())
