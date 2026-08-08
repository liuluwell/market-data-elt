{{
  config(
    materialized='table'
  )
}}

-- Per-stock daily summary: adds analysis-friendly derived metrics on top of the cleaned detail data.
-- Materialized as a table (not a view) because the marts layer is used for analysis/queries,
-- and a physical table is faster to query.

select
    symbol,
    trade_date,
    open_price,
    close_price,
    high_price,
    low_price,
    volume,
    amount,
    pct_change,
    amplitude,
    turnover_rate,

    -- Derived metric 1: whether the stock rose or fell today (for counting advancers)
    case
        when pct_change > 0 then 'up'
        when pct_change < 0 then 'down'
        else 'flat'
    end as price_direction,

    -- Derived metric 2: daily average price (estimated as amount / shares; volume is in lots, so x100 to get shares)
    case
        when volume > 0 then round(amount / (volume * 100), 2)
        else null
    end as avg_price

from {{ ref('stg_stock_daily') }}