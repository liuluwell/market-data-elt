import akshare as ak
for symbol in ["sz000001", "sh600519", "sz300750"]:
    df = ak.stock_zh_a_hist_tx(symbol=symbol, start_date="20250101", end_date="20260725", adjust="")
    print(f"=== {symbol} ===")
    print(df.columns.tolist())
    print(df.head(2))