"""HTTP 工具：重試、依網站控制請求間隔，避免被證交所等網站暫時封鎖。"""
import http.client
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# 每個網站兩次請求之間至少間隔幾秒。證交所對短時間大量請求會暫時封鎖 IP，所以間隔最長。
MIN_GAP = {
    "www.twse.com.tw": 3.5,
    "openapi.twse.com.tw": 1.0,
    "www.tpex.org.tw": 2.5,
    "opendata.tdcc.com.tw": 1.0,
    "www.tdcc.com.tw": 0.8,
    "www.taifex.com.tw": 2.0,
}
_last_hit = {}

# 櫃買中心的憑證缺少 Authority Key Identifier，新版 Python 的嚴格模式會拒絕。
# 這裡只放寬這一項格式檢查，憑證鏈與主機名稱照常驗證。
_RELAXED = ssl.create_default_context()
if hasattr(ssl, "VERIFY_X509_STRICT"):
    _RELAXED.verify_flags &= ~ssl.VERIFY_X509_STRICT


class FetchError(Exception):
    pass


def _pace(host):
    gap = MIN_GAP.get(host, 1.0)
    wait = _last_hit.get(host, 0) + gap - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.monotonic()


def fetch(url, data=None, opener=None, retries=4, timeout=60, headers=None):
    """下載網址並回傳 bytes。網路錯誤、逾時或伺服器錯誤會等一下再重試。"""
    host = urllib.parse.urlparse(url).hostname or ""
    hdrs = {"User-Agent": UA, "Accept": "application/json, text/plain, text/html, */*",
            "Accept-Language": "zh-TW,zh;q=0.9"}
    hdrs.update(headers or {})
    body = urllib.parse.urlencode(data).encode() if isinstance(data, dict) else data
    last = None
    for attempt in range(1, retries + 1):
        _pace(host)
        req = urllib.request.Request(url, data=body, headers=hdrs)
        try:
            if opener:
                resp = opener.open(req, timeout=timeout)
            else:
                ctx = _RELAXED if host.endswith("tpex.org.tw") else None
                resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
            with resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (400, 401, 404):
                raise FetchError(f"{e.code} {url}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException, OSError) as e:
            last = e
        if attempt < retries:
            wait = 10 * attempt
            print(f"  連線失敗（{last}），{wait} 秒後重試：{url.split('?')[0]}", flush=True)
            time.sleep(wait)
    raise FetchError(f"{last} {url}")


def decode(raw):
    for enc in ("utf-8-sig", "cp950", "big5"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def get_json(url, retries=4):
    """下載 JSON。網站偶爾回傳 HTML 錯誤頁（例如請求太頻繁），這時也視為失敗並重試。"""
    last = None
    for attempt in range(1, retries + 1):
        text = decode(fetch(url, retries=retries))
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            last = e
            if attempt < retries:
                wait = 20 * attempt
                print(f"  回傳的不是 JSON（可能被限流），{wait} 秒後重試：{url.split('?')[0]}", flush=True)
                time.sleep(wait)
    raise FetchError(f"非 JSON 回應：{url}（{last}）")


def get_text(url, retries=4):
    return decode(fetch(url, retries=retries))
