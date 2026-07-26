import akshare as ak
import time
import random
from requests.exceptions import ConnectionError, ReadTimeout

def get_stock_info_with_retry(symbol, max_retries=5):
    """
    带重试机制获取个股信息
    :param symbol: 股票代码
    :param max_retries: 最大重试次数
    :return: DataFrame
    """
    for i in range(max_retries):
        try:
            # 核心调用
            df = ak.stock_individual_info_em(symbol=symbol)
            return df
        except (ConnectionError, ReadTimeout, Exception) as e:
            print(f"第 {i+1} 次请求失败: {e}")
            if i < max_retries - 1:
                # 指数退避 + 随机抖动，避免规律性请求被封锁
                wait_time = (2 ** i) + random.uniform(0, 1)
                print(f"等待 {wait_time:.2f} 秒后重试...")
                time.sleep(wait_time)
            else:
                raise Exception(f"经过 {max_retries} 次重试后仍无法获取数据")

if __name__ == '__main__':
    try:
        # 使用封装好的函数调用
        stock_df = get_stock_info_with_retry(symbol="000001")
        print(stock_df)
    except Exception as e:
        print(f"最终失败: {e}")
