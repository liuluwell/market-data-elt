import akshare as ak

for code, prefix in [("000001","sz"), ("600519","sh")]:
    df = ak.stock_zh_a_hist_tx(symbol=f"{prefix}{code}", start_date="20250804", end_date="20250804", adjust="")
    vol = df["volume"].values[0]
    amt = df["amount"].values[0]
    print(f"\n{code}: 原始volume={vol}, amount={amt}")
    print(f"  amount/volume       = {amt/vol:.2f}")       # 假设volume是股
    print(f"  amount/(volume*100) = {amt/(vol*100):.2f}") # 假设volume是手