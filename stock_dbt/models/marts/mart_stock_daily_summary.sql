{{
  config(
    materialized='table'
  )
}}

-- 个股每日指标汇总:在清洗后的明细基础上,补充一些便于分析的衍生指标
-- 物化为 table(不是 view),因为 marts 层是给分析/查询用的,物化成表查询更快

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

    -- 衍生指标1:当日是涨还是跌(便于统计上涨家数)
    case
        when pct_change > 0 then 'up'
        when pct_change < 0 then 'down'
        else 'flat'
    end as price_direction,

    -- 衍生指标2:当日均价(用成交额/成交量估算,注意成交量单位是手,要乘100换成股)
    case
        when volume > 0 then round(amount / (volume * 100), 2)
        else null
    end as avg_price

from {{ ref('stg_stock_daily') }}