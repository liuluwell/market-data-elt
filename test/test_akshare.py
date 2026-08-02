import requests

url = "https://push2.eastmoney.com/api/qt/stock/get?fltt=2&invt=2&fields=f43&secid=0.000001"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 Chrome/120 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/"
}


s = requests.Session()
s.trust_env = False

r = s.get(
    url,
    headers=headers,
    timeout=10
)

print(r.status_code)
print(r.text[:500])