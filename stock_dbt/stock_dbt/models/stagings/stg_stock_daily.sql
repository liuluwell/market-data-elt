{{
  config(
    materialized='view'
  )
}}

-- staging layer: clean and standardize the raw market data
-- rename fields to English and filter out obviously invalid records

select
    symbol,
    trade_date,
    open        as open_price,
    close       as close_price,
    high        as high_price,
    low         as low_price,
    volume,
    amount,
    amplitude,
    pct_change,
    price_change,
    turnover_rate,
    data_source,
    fetched_at

from {{ source('raw', 'raw_stock_daily') }}

-- basic data quality filter: exclude clearly unreasonable records
where close > 0
  and open > 0
  and high >= low