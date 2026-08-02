CREATE TABLE IF NOT EXISTS raw_stock_daily (
    id             bigserial PRIMARY KEY,
    symbol         text NOT NULL,
    trade_date     date NOT NULL,
    open           numeric,
    close          numeric,
    high           numeric,
    low            numeric,
    volume         numeric,      -- 统一单位:手
    amount         numeric,      -- 统一单位:元
    amplitude      numeric,      -- 振幅(%),自行计算
    pct_change     numeric,      -- 涨跌幅(%),自行计算
    price_change   numeric,      -- 涨跌额,自行计算
    turnover_rate  numeric,      -- 换手率(%),仅东财提供,腾讯为NULL
    data_source    text,         -- 记录这条数据来自哪个数据源,便于追溯
    fetched_at     timestamp DEFAULT now(),
    UNIQUE(symbol, trade_date)
);