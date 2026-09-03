# -*- coding: utf-8 -*-
"""
Flow Radar - 국내 실전 데이터 어댑터

이 백테스트는 원격 환경의 방화벽 때문에 KRX/네이버/야후에 접속하지 못했고,
'외국인 순매수'를 원/달러 환율로 대체(프록시)해서 검증했다.

사용자 PC(또는 회사 서버)에서는 진짜 수급 데이터를 쓸 수 있다.
이 파일은 그 교체 지점을 정확히 표시한 어댑터다.

  pip install pykrx pandas

핵심 아이디어
-------------
FLOW 층(자금방향)이 IC 분석에서 한국 시장의 유일한 안정적 알파원이었다.
환율 프록시로도 60일 IC 0.11 이 나왔으므로, 진짜 수급 데이터를 넣으면
이 층의 신호 대 잡음비가 올라갈 여지가 크다. 다음 3개를 추가한다.

  FLOW.foreign_net : 외국인 코스피 순매수 20일 누적 / 시가총액
  FLOW.inst_net    : 기관 코스피 순매수 20일 누적 / 시가총액
  FLOW.credit_bal  : 신용융자잔고 증감 (개인 레버리지 = 과열 역지표)

주의
----
KRX 투자자별 매매동향은 장 마감 후(대략 18시) 확정된다.
따라서 t일 수급으로 t+1일 포지션을 잡는 것은 실행 가능하다(look-ahead 아님).
반대로 t일 장중에 t일 수급을 쓰는 코드는 절대 쓰면 안 된다.
"""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

KOSPI_IDX = "1001"
KOSDAQ_IDX = "2001"


# ---------------------------------------------------------------------------
# 1) 지수 OHLCV
# ---------------------------------------------------------------------------

def kr_index_ohlcv(start: str, end: str, ticker: str = KOSPI_IDX) -> pd.DataFrame:
    """코스피/코스닥 지수 일봉. pykrx 사용."""
    from pykrx import stock
    df = stock.get_index_ohlcv_by_date(start, end, ticker)
    df.index.name = "date"
    return df.rename(columns={"시가": "open", "고가": "high", "저가": "low",
                              "종가": "close", "거래량": "volume",
                              "거래대금": "value"})


# ---------------------------------------------------------------------------
# 2) 투자자별 수급  <- 이 프로젝트의 환율 프록시를 대체하는 진짜 데이터
# ---------------------------------------------------------------------------

def kr_investor_flow(start: str, end: str, market: str = "KOSPI") -> pd.DataFrame:
    """
    투자자별 순매수 대금(원). 일자 인덱스, 컬럼: 외국인 / 기관합계 / 개인.

    pykrx 의 get_market_trading_value_by_date 는 한 번에 긴 구간을 주지 않는
    경우가 있어 연 단위로 끊어 호출한다.
    """
    from pykrx import stock

    s, e = pd.Timestamp(start), pd.Timestamp(end)
    frames = []
    cur = s
    while cur <= e:
        nxt = min(cur + pd.DateOffset(years=1) - pd.Timedelta(days=1), e)
        d = stock.get_market_trading_value_by_date(
            cur.strftime("%Y%m%d"), nxt.strftime("%Y%m%d"), market)
        frames.append(d)
        cur = nxt + pd.Timedelta(days=1)

    out = pd.concat(frames).sort_index()
    out = out[~out.index.duplicated(keep="last")]
    out.index.name = "date"
    keep = [c for c in ("외국인합계", "기관합계", "개인") if c in out.columns]
    return out[keep].rename(columns={"외국인합계": "foreign", "기관합계": "inst",
                                     "개인": "retail"})


def kr_market_cap(start: str, end: str, market: str = "KOSPI") -> pd.Series:
    """시가총액 일별 합계. 순매수 금액을 규모로 나누기 위한 분모."""
    from pykrx import stock
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    rows = {}
    for d in pd.bdate_range(s, e, freq="BME"):      # 월말만 조회 후 보간
        try:
            cap = stock.get_market_cap_by_ticker(d.strftime("%Y%m%d"), market)
            rows[d] = float(cap["시가총액"].sum())
        except Exception:
            continue
    return pd.Series(rows).sort_index()


# ---------------------------------------------------------------------------
# 3) Flow Radar 지표로 변환
# ---------------------------------------------------------------------------

def flow_layer_kr(flow: pd.DataFrame, mcap: pd.Series,
                  window: int = 20) -> pd.DataFrame:
    """
    수급 원자료 → 시그마 단위 지표.

    순매수 대금은 절대금액이라 그대로 쓰면 시장 규모가 커질수록 값이 커진다.
    시가총액으로 나눠 '유통주식 대비 몇 %가 손바뀜했나'로 바꾼 뒤,
    자기 자신의 과거 변동성으로 표준화한다.
    """
    cap = mcap.reindex(flow.index).ffill().bfill()
    out = {}
    for who, name in (("foreign", "FLOW.foreign_net"), ("inst", "FLOW.inst_net")):
        if who not in flow.columns:
            continue
        ratio = flow[who].rolling(window).sum() / cap
        sd = ratio.rolling(250).std()
        out[name] = (ratio / sd.replace(0.0, np.nan)).clip(-3, 3)

    # 개인 순매수는 역지표로 쓴다 (개인이 살수록 위험선호 과열)
    if "retail" in flow.columns:
        ratio = flow["retail"].rolling(window).sum() / cap
        sd = ratio.rolling(250).std()
        out["FLOW.retail_inv"] = (-ratio / sd.replace(0.0, np.nan)).clip(-3, 3)

    return pd.DataFrame(out)


def build_kr_panel(start: str = "2005-01-01",
                   end: str | None = None) -> dict[str, pd.DataFrame]:
    """
    실전용 한국 패널 조립.
    반환된 flow_signals 를 flow_radar.build_signals() 결과에 concat 하면
    FLOW 층에 진짜 수급이 들어간다.
    """
    end = end or dt.date.today().strftime("%Y-%m-%d")
    px = kr_index_ohlcv(start.replace("-", ""), end.replace("-", ""))
    flow = kr_investor_flow(start, end)
    mcap = kr_market_cap(start, end)
    return {
        "price": px,
        "flow_raw": flow,
        "flow_signals": flow_layer_kr(flow, mcap),
    }


# ---------------------------------------------------------------------------
# 4) 한국투자증권(KIS) API - 실시간 운용 시
# ---------------------------------------------------------------------------
"""
장중 실시간으로 돌릴 때는 pykrx(웹 스크래핑) 대신 KIS OpenAPI 를 쓴다.

  - 국내주식 투자자별 매매동향 : /uapi/domestic-stock/v1/quotations/inquire-investor
  - 업종별 시세               : /uapi/domestic-stock/v1/quotations/inquire-index-price
  - 프로그램매매 동향          : /uapi/domestic-stock/v1/quotations/inquire-program-trade-by-stock

운용 루틴 권장안
  16:00  장마감
  18:10  KRX 수급 확정 → flow_layer_kr() 갱신
  18:20  Flow Score 재계산 → 레짐 판정
  다음날 09:00~09:10  목표비중과 실제비중 차이를 분할 체결

주간 리밸런싱이 백테스트에서 월간보다 뚜렷하게 우월했으므로
(KOSPI 샤프 0.31 → 0.50), 판정은 매일 하되 매매는 금요일 종가 기준
주 1회로 묶는 것을 기본값으로 권한다.
"""
