"""
fetch_stock.py —— 抓取股票日线行情,存入 raw_stock_daily。

设计要点:
1. 只抓最近 LOOKBACK_DAYS 天的数据,避免一次性拉全部历史
2. 字段严格按 akshare 实际返回的中文列名取值,避免顺序错位
3. ON CONFLICT 实现幂等:重跑不产生重复数据
4. 单只股票失败不影响其他股票
"""
import os
import time
import logging
from datetime import datetime, timedelta

from dotenv import load_dotenv
import akshare as ak
import psycopg

from ingestion.config import STOCK_POOL, LOOKBACK_DAYS, REQUEST_INTERVAL

# ---- 加载配置 ----
load_dotenv()

DB_CONFIG = dict(
    host=os.getenv("DB_HOST"),
    port=os.getenv("DB_PORT"),
    dbname=os.getenv("DB_NAME"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD"),
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


def fetch_one_stock(symbol: str, start_date: str, end_date: str):
    """抓单只股票指定时间范围的日线数据。失败返回 None,不抛异常。"""
    try:
        df = ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust=""
        )
        logger.info(f"抓取 {symbol} 成功,共 {len(df)} 条数据")
        return df
    except Exception as e:
        logger.error(f"抓取 {symbol} 失败:{e}")
        return None


def insert_stock_data(conn, symbol: str, df):
    """把一只股票的 DataFrame 存进数据库,ON CONFLICT 实现幂等。"""
    if df is None or df.empty:
        return 0

    rows_inserted = 0
    with conn.cursor() as cur:
        for _, row in df.iterrows():
            cur.execute(
                """
                INSERT INTO raw_stock_daily
                    (symbol, trade_date, open, close, high, low,
                     volume, amount, amplitude, pct_change, price_change, turnover_rate)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, trade_date)
                DO UPDATE SET
                    open = EXCLUDED.open,
                    close = EXCLUDED.close,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    volume = EXCLUDED.volume,
                    amount = EXCLUDED.amount,
                    amplitude = EXCLUDED.amplitude,
                    pct_change = EXCLUDED.pct_change,
                    price_change = EXCLUDED.price_change,
                    turnover_rate = EXCLUDED.turnover_rate,
                    fetched_at = now();
                """,
                (
                    symbol,
                    row["日期"],
                    row["开盘"],
                    row["收盘"],
                    row["最高"],
                    row["最低"],
                    row["成交量"],
                    row["成交额"],
                    row["振幅"],
                    row["涨跌幅"],
                    row["涨跌额"],
                    row["换手率"],
                )
            )
            rows_inserted += 1
    conn.commit()
    return rows_inserted


def main():
    start_time = datetime.now()

    # 计算抓取的时间范围:最近 LOOKBACK_DAYS 天
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")

    conn = psycopg.connect(**DB_CONFIG)

    total_rows = 0
    success_count = 0
    fail_count = 0

    for symbol in STOCK_POOL:
        df = fetch_one_stock(symbol, start_date, end_date)
        if df is None:
            fail_count += 1
            continue

        rows = insert_stock_data(conn, symbol, df)
        total_rows += rows
        success_count += 1

        time.sleep(REQUEST_INTERVAL)  # 别把接口打太狠

    conn.close()
    elapsed = (datetime.now() - start_time).total_seconds()

    logger.info(
        f"运行完成:成功 {success_count} 只,失败 {fail_count} 只,"
        f"共处理 {total_rows} 条记录,耗时 {elapsed:.1f} 秒"
    )


if __name__ == "__main__":
    main()