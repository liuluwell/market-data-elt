STOCK_POOL = ["000001", "600519", "300750"]
LOOKBACK_DAYS = 365
REQUEST_INTERVAL = 2          # 请求间隔拉长到2秒,保护接口

# 数据源优先级:先尝试第一个,失败了自动尝试下一个
DATA_SOURCE_PRIORITY = ["tx", "em"]   # 腾讯优先,东财备用