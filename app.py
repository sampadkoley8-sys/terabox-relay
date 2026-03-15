"""
TeraBox Relay Proxy — Deploy on Render.com (free tier)
Relays TeraBox download API requests from HF Space.
HF Space's datacenter IP is CF-blocked, but Render's IP is not.
"""
import os
import json
import time
import threading
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Free cookies from tera.backend.live
_free_cookies = []
_cookies_lock = threading.Lock()
_cookies_fetched = 0

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# API sites to try (in order)
API_SITES = [
    "https://teraboxdl.site/api/proxy",
    "https://tera-downloader.com/api/proxy",
    "https://1024teradl.com/api/proxy",
    "https://playterabox.com/api/proxy",
    "https://theteraboxdownloader.com/api/proxy",
    "https://getodata.com/api/proxy",
    "https://freeterabox.com/api/proxy",
    "https://saveterabox.com/api/proxy",
    "https://teraboxfast.com/api/proxy",
    "https://teraboxdl.online/api/proxy",
]


def _refresh_cookies():
    """Fetch free cookies from tera.backend.live."""
    global _free_cookies, _cookies_fetched
    try:
        r = requests.get("https://tera.backend.live/cookies-list", timeout=10)
        if r.status_code == 200:
            cookies = r.json()
            with _cookies_lock:
                _free_cookies = cookies if isinstance(cookies, list) else []
                _cookies_fetched = time.time()
            print(f"[RELAY] Fetched {len(_free_cookies)} free cookies")
    except Exception as e:
        print(f"[RELAY] Cookie fetch failed: {e}")


def _get_cookie():
    """Get a free ndus cookie."""
    with _cookies_lock:
        if not _free_cookies or time.time() - _cookies_fetched > 600:
            pass  # Will refresh below
        else:
            import random
            return random.choice(_free_cookies)
    _refresh_cookies()
    with _cookies_lock:
        if _free_cookies:
            import random
            return random.choice(_free_cookies)
    return ""


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "terabox-relay",
        "cookies": len(_free_cookies),
        "timestamp": int(time.time()),
    })


@app.route("/resolve", methods=["GET", "POST"])
def resolve():
    """Resolve a TeraBox share URL to download links.
    GET: ?url=https://teraboxapp.com/s/1xxx or ?surl=1xxx
    POST: {"url": "https://teraboxapp.com/s/1xxx"} or {"surl": "1xxx"}
    """
    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
        url = data.get("url", "")
        surl = data.get("surl", "")
    else:
        url = request.args.get("url", "")
        surl = request.args.get("surl", "")

    if not url and surl:
        surl = surl.lstrip("1")
        url = f"https://teraboxapp.com/s/1{surl}"

    if not url:
        return jsonify({"error": "Missing url or surl parameter"}), 400

    # Normalize URL
    if "/s/" not in url and surl:
        url = f"https://teraboxapp.com/s/1{surl.lstrip('1')}"

    # Try share URL variants
    share_urls = [url]
    if "teraboxapp.com" in url:
        share_urls.append(url.replace("teraboxapp.com", "terabox.com"))
        share_urls.append(url.replace("teraboxapp.com", "1024terabox.com"))
    elif "terabox.com" in url and "1024" not in url:
        share_urls.append(url.replace("terabox.com", "teraboxapp.com"))

    # Try each API site
    for api_url in API_SITES:
        origin = api_url.rsplit("/api", 1)[0]
        for share_url in share_urls:
            try:
                r = requests.post(
                    api_url,
                    json={"url": share_url},
                    headers={
                        "Content-Type": "application/json",
                        "Origin": origin,
                        "Referer": origin + "/",
                        "User-Agent": BROWSER_UA,
                        "Accept": "application/json, text/plain, */*",
                    },
                    timeout=20,
                )
                if r.status_code == 403 and "text/html" in r.headers.get("content-type", ""):
                    break  # CF block, skip this site
                if r.status_code != 200:
                    break

                data = r.json()
                errno = data.get("errno", -1)
                if errno != 0:
                    continue  # Try next share URL

                file_list = data.get("list", [])
                results = []
                for it in file_list:
                    if str(it.get("isdir", "0")) == "1":
                        continue
                    fn = it.get("server_filename") or it.get("name") or "file"
                    sz = int(it.get("size", 0))
                    dlink = str(it.get("dlink", "")).strip()
                    if not dlink or not dlink.startswith("http"):
                        dlink = str(it.get("direct_link", "")).strip()
                    if dlink and dlink.startswith("http"):
                        results.append({
                            "filename": fn,
                            "size": sz,
                            "dlink": dlink,
                        })

                if results:
                    return jsonify({
                        "status": "ok",
                        "source": origin.replace("https://", ""),
                        "files": results,
                    })

            except requests.exceptions.ConnectionError:
                break  # DNS fail, skip site
            except Exception:
                continue

    return jsonify({"status": "error", "message": "All APIs failed"}), 502


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "service": "TeraBox Relay Proxy",
        "endpoints": {
            "/health": "Health check",
            "/resolve?url=<terabox_url>": "GET - Resolve TeraBox URL",
            "/resolve": "POST - {url: <terabox_url>}",
        },
        "status": "running",
    })


# Refresh cookies on startup
_refresh_cookies()

# Auto-refresh cookies every 10 min
def _cookie_refresher():
    while True:
        time.sleep(600)
        _refresh_cookies()

threading.Thread(target=_cookie_refresher, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
