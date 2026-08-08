"""
fetch_stock.py — Fetch daily stock market data and load into raw_stock_daily.

Design notes:
1. Multiple data sources with automatic fallback (if one fails, try the next by priority).
2. Fields and units are normalized, so the format stored in the DB is consistent
   regardless of which source the data came from.
3. Daily change / price change / amplitude are computed in-pipeline, not relying on
   whether the source provides them.
4. ON CONFLICT provides idempotency; a single failed stock does not affect the others.

Note: The Chinese strings in df.rename() and row[...] below are the actual column names
returned by the akshare API (e.g. "日期" = date, "开盘" = open). They must NOT be translated,
or the code will break. English meaning is annotated in comments.
"""
import os
import time
import logging
from datetime import datetime, timedelta
import math
import numpy as np


from dotenv import load_dotenv
import akshare as ak
import pandas as pd
import psycopg

from ingestion.config import STOCK_POOL, LOOKBACK_DAYS, REQUEST_INTERVAL, DATA_SOURCE_PRIORITY

load_dotenv()

DB_CONFIG = dict(
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def safe_value(v):
    """Convert NaN/None uniformly to Python None, to avoid NaN being stored as a string in the DB."""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return v

def to_market_prefixed_symbol(symbol: str) -> str:
    """Convert a plain numeric code to the market-prefixed format required by the Tencent/Sina APIs."""
    if symbol.startswith(("0", "3")):
        return f"sz{symbol}"
    elif symbol.startswith("6"):
        return f"sh{symbol}"
    raise ValueError(f"Cannot determine the exchange for stock code {symbol}")


def add_derived_fields(df: pd.DataFrame) -> pd.DataFrame:
    # Column names below ("日期"=date, "收盘"=close, "最高"=high, "最低"=low) are akshare's
    # returned column names and must stay as-is.
    df = df.sort_values("日期").reset_index(drop=True)
    prev_close = df["收盘"].shift(1)

    df["涨跌额"] = (df["收盘"] - prev_close).round(2)                        # price_change
    df["涨跌幅"] = ((df["涨跌额"] / prev_close) * 100).round(2)               # pct_change
    df["振幅"] = (((df["最高"] - df["最低"]) / prev_close) * 100).round(2)    # amplitude

    # Key: replace all NaN with None so the DB stores SQL NULL rather than the string "NaN".
    df = df.replace({np.nan: None})
    return df


def fetch_from_em(symbol: str, start_date: str, end_date: str):
    """EastMoney data source."""
    df = ak.stock_zh_a_hist(
        symbol=symbol, period="daily",
        start_date=start_date, end_date=end_date, adjust=""
    )
    df = df.rename(columns={"涨跌幅": "_em_pct", "涨跌额": "_em_chg", "振幅": "_em_amp"})
    df = add_derived_fields(df)  # compute in-pipeline to keep the same basis as Tencent, not EastMoney's own values
    df["turnover_rate"] = df["换手率"]   # "换手率" = turnover rate
    df["data_source"] = "em"
    return df


def fetch_from_tx(symbol: str, start_date: str, end_date: str):
    """Tencent data source. Column names and units need to be aligned to the standard format."""
    tx_symbol = to_market_prefixed_symbol(symbol)
    df = ak.stock_zh_a_hist_tx(
        symbol=tx_symbol, start_date=start_date, end_date=end_date, adjust=""
    )
    # Rename Tencent's English columns to the same Chinese column names used internally
    # (aligning with the EastMoney source so downstream code is source-agnostic).
    df = df.rename(columns={
        "date": "日期", "open": "开盘", "close": "收盘",
        "high": "最高", "low": "最低", "amount": "成交额",
    })
    df["成交量"] = df["volume"] / 100          # shares -> lots, aligned with EastMoney's unit
    df["换手率"] = df["turnover"] * 100         # decimal -> percentage, aligned with EastMoney
    df = add_derived_fields(df)                # compute daily change etc.
    df["turnover_rate"] = df["换手率"]
    df["data_source"] = "tx"
    return df


DATA_SOURCE_MAP = {"em": fetch_from_em, "tx": fetch_from_tx}


def fetch_one_stock(symbol: str, start_date: str, end_date: str):
    """
    Try data sources in priority order; if one fails, automatically try the next.
    Returns None only if all sources fail.
    """
    for source in DATA_SOURCE_PRIORITY:
        fetch_func = DATA_SOURCE_MAP[source]
        try:
            df = fetch_func(symbol, start_date, end_date)
            logger.info(f"[{source}] Fetched {symbol} successfully, {len(df)} rows")
            return df
        except Exception as e:
            logger.warning(f"[{source}] Failed to fetch {symbol}, trying next source: {e}")
    logger.error(f"All data sources failed for {symbol}")
    return None


def insert_stock_data(conn, symbol: str, df):
    if df is None or df.empty:
        return 0
    rows_inserted = 0
    with conn.cursor() as cur:
        for _, row in df.iterrows():
            cur.execute(
                """
                INSERT INTO raw_stock_daily
                    (symbol, trade_date, open, close, high, low,
                     volume, amount, amplitude, pct_change, price_change,
                     turnover_rate, data_source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, trade_date)
                DO UPDATE SET
                    open = EXCLUDED.open, close = EXCLUDED.close,
                    high = EXCLUDED.high, low = EXCLUDED.low,
                    volume = EXCLUDED.volume, amount = EXCLUDED.amount,
                    amplitude = EXCLUDED.amplitude, pct_change = EXCLUDED.pct_change,
                    price_change = EXCLUDED.price_change,
                    turnover_rate = EXCLUDED.turnover_rate,
                    data_source = EXCLUDED.data_source,
                    fetched_at = now();
                """,
                (
                    # Chinese keys below are akshare column names — do not translate.
                    symbol, safe_value(row["日期"]), safe_value(row["开盘"]), safe_value(row["收盘"]),
                    safe_value(row["最高"]), safe_value(row["最低"]), safe_value(row["成交量"]),
                    safe_value(row["成交额"]), safe_value(row["振幅"]), safe_value(row["涨跌幅"]),
                    safe_value(row["涨跌额"]), safe_value(row["turnover_rate"]), row["data_source"]
                )
            )
            rows_inserted += 1
    conn.commit()
    return rows_inserted


def main():
    start_time = datetime.now()
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")

    conn = psycopg.connect(**DB_CONFIG)
    total_rows, success_count, fail_count = 0, 0, 0

    for symbol in STOCK_POOL:
        df = fetch_one_stock(symbol, start_date, end_date)
        if df is None:
            fail_count += 1
            continue
        rows = insert_stock_data(conn, symbol, df)
        total_rows += rows
        success_count += 1
        time.sleep(REQUEST_INTERVAL)

    conn.close()
    elapsed = (datetime.now() - start_time).total_seconds()
    logger.info(
        f"Run complete: {success_count} succeeded, {fail_count} failed, "
        f"{total_rows} rows processed, elapsed {elapsed:.1f}s"
    )


if __name__ == "__main__":
    main()