
CREATE TABLE IF NOT EXISTS raw_stock_daily (
    id             bigserial PRIMARY KEY,
    symbol         text NOT NULL,
    trade_date     date NOT NULL,
    open           numeric,
    close          numeric,
    high           numeric,
    low            numeric,
    volume         numeric,      -- unit: lot (100 shares)
    amount         numeric,      -- unit: CNY
    amplitude      numeric,      -- amplitude (%), computed in-pipeline
    pct_change     numeric,      -- daily change (%), computed in-pipeline
    price_change   numeric,      -- daily price change, computed in-pipeline
    turnover_rate  numeric,      -- turnover rate (%); provided by EastMoney only, NULL for Tencent
    data_source    text,         -- which source this record came from, for traceability
    fetched_at     timestamp DEFAULT now(),
    UNIQUE(symbol, trade_date)
);