{{
  config(
    materialized='view'
  )
}}

-- staging 层:对原始行情数据做清洗和标准化
-- 字段从中文改为英文命名,过滤明显异常数据

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

-- 基本的数据质量过滤:排除掉明显不合理的记录
where close > 0
  and open > 0
  and high >= low