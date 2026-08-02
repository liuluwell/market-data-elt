"""
fetch_stock.py —— 抓取股票日线行情,存入 raw_stock_daily。

设计要点:
1. 多数据源,按优先级自动降级(当前一个失败,自动试下一个)
2. 统一字段和单位,不管用哪个数据源,存进数据库的格式一致
3. 涨跌幅/涨跌额/振幅 自行计算,不依赖数据源是否提供
4. ON CONFLICT 实现幂等,单只股票失败不影响其他
"""
import os
import time
import logging
from datetime import datetime, timedelta
import math


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
    """把 NaN/None 统一转成 Python 的 None,避免 NaN 被当成字符串存进数据库。"""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return v

def to_market_prefixed_symbol(symbol: str) -> str:
    """纯数字代码转带市场前缀的格式(腾讯/新浪接口需要)。"""
    if symbol.startswith(("0", "3")):
        return f"sz{symbol}"
    elif symbol.startswith("6"):
        return f"sh{symbol}"
    raise ValueError(f"无法判断股票代码 {symbol} 所属交易所")


def add_derived_fields(df: pd.DataFrame) -> pd.DataFrame:
    """
    自行计算涨跌幅、涨跌额、振幅,不依赖数据源是否提供这些字段。
    需要按日期排序后,用前一天收盘价(shift)计算。
    """
    df = df.sort_values("日期").reset_index(drop=True)
    prev_close = df["收盘"].shift(1)

    df["涨跌额"] = df["收盘"] - prev_close
    df["涨跌幅"] = (df["涨跌额"] / prev_close * 100).round(2)
    df["振幅"] = ((df["最高"] - df["最低"]) / prev_close * 100).round(2)

    # 第一行没有"前一天"数据,涨跌相关字段自然是 NaN,转成 None 方便入库
    df = df.where(pd.notnull(df), None)
    return df


def fetch_from_em(symbol: str, start_date: str, end_date: str):
    """东方财富数据源。"""
    df = ak.stock_zh_a_hist(
        symbol=symbol, period="daily",
        start_date=start_date, end_date=end_date, adjust=""
    )
    df = df.rename(columns={"涨跌幅": "_em_pct", "涨跌额": "_em_chg", "振幅": "_em_amp"})
    df = add_derived_fields(df)  # 自算,保证和腾讯口径一致,不用东财自带的
    df["turnover_rate"] = df["换手率"]
    df["data_source"] = "em"
    return df


def fetch_from_tx(symbol: str, start_date: str, end_date: str):
    """腾讯数据源。字段名、单位需要对齐到标准格式。"""
    tx_symbol = to_market_prefixed_symbol(symbol)
    df = ak.stock_zh_a_hist_tx(
        symbol=tx_symbol, start_date=start_date, end_date=end_date, adjust=""
    )
    df = df.rename(columns={
        "date": "日期", "open": "开盘", "close": "收盘",
        "high": "最高", "low": "最低", "amount": "成交额",
    })
    df["成交量"] = df["volume"]          # 股 -> 手,和东财口径对齐 腾讯的接口单位本来就是手
    df["换手率"] = df["turnover"] * 100         # 小数 -> 百分比,和东财口径对齐
    df = add_derived_fields(df)                # 自算涨跌幅等
    df["turnover_rate"] = df["换手率"]
    df["data_source"] = "tx"
    return df


DATA_SOURCE_MAP = {"em": fetch_from_em, "tx": fetch_from_tx}


def fetch_one_stock(symbol: str, start_date: str, end_date: str):
    """
    按优先级依次尝试数据源,前一个失败自动尝试下一个。
    全部失败才返回 None。
    """
    for source in DATA_SOURCE_PRIORITY:
        fetch_func = DATA_SOURCE_MAP[source]
        try:
            df = fetch_func(symbol, start_date, end_date)
            logger.info(f"[{source}] 抓取 {symbol} 成功,共 {len(df)} 条数据")
            return df
        except Exception as e:
            logger.warning(f"[{source}] 抓取 {symbol} 失败,尝试下一数据源:{e}")
    logger.error(f"抓取 {symbol} 所有数据源均失败")
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
        f"运行完成:成功 {success_count} 只,失败 {fail_count} 只,"
        f"共处理 {total_rows} 条记录,耗时 {elapsed:.1f} 秒"
    )


if __name__ == "__main__":
    main()