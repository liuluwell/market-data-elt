-- 2. 股票基本信息(低频更新,含板块/行业)
CREATE TABLE IF NOT EXISTS raw_stock_basic_info (
    symbol       text PRIMARY KEY,
    name         text,
    industry     text,
    list_date    date,
    updated_at   timestamp DEFAULT now()
);