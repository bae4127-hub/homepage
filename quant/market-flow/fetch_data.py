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

    # 각 통화를 "1달러당 통화단위"의 로그값으로 통일 → 오르면 달러 강세
    parts, wsum = [], 0.0
    for c, w in DXY_WEIGHTS.items():
        if c not in wide.columns:
            continue
        x = wide[c].astype(float)
        parts.append(np.log(x) * w)  # 오르면 달러 강세
        wsum += w
    dxy_log = pd.concat(parts, axis=1).sum(axis=1, min_count=len(parts)) / wsum
    dxy = np.exp(dxy_log)
    dxy = 100.0 * dxy / dxy.dropna().iloc[0]

    out = pd.DataFrame({"USDKRW": wide.get("South Korea"), "DXY": dxy})
    out.index.name = "date"
    return out.dropna(how="all")


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
    print("[1/4] 선물 연결가격 (pysystemtrade)")
    fut = fetch_futures()
    _save(fut, "futures_daily.csv")

    print("[2/4] 연준 H.10 환율")
    fx = fetch_fx()
    print(f"  USDKRW {fx['USDKRW'].dropna().index.min().date()} ~ {fx['USDKRW'].dropna().index.max().date()}")
    _save(fx, "fx_daily.csv")

    print("[3/4] VIX 현물")
    vix = fetch_vix_spot()
    _save(vix, "vix_daily.csv")

    print("[4/4] S&P500 월간 (Shiller)")
    spm = fetch_sp500_monthly()
    _save(spm, "sp500_monthly.csv")

    print("\n완료. data/ 에 4개 파일 저장")
    return 0


if __name__ == "__main__":
    sys.exit(main())
