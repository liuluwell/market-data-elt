STOCK_POOL = ["000001", "600519", "300750"]
LOOKBACK_DAYS = 365
REQUEST_INTERVAL = 2          # request interval extended to 2s to protect the API

# Data source priority: try the first; if it fails, automatically try the next
DATA_SOURCE_PRIORITY = ["tx", "em"]   # Tencent primary, EastMoney fallback
