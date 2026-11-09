#!/usr/bin/env python3
"""国家市场监管总局 · 企业名称开放查询（免登录）

用法:
    python3 check_national.py 靛穹纪 萤穹纪 --trade 科技 --out national.json
    python3 check_national.py --file names.txt --trade 科技
"""
import argparse
import http.cookiejar
import json
import re
import time
import urllib.parse
import urllib.request

BASE = "http://wsdj.samr.gov.cn/saicmccx/"
API = BASE + "query/home"
UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Referer": BASE,
}


def make_opener():
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = list(UA.items())
    return opener


def get_token(opener):
    html = opener.open(BASE, timeout=20).read().decode("utf-8", "ignore")
    m = re.search(r'id="token"\s+value="([^"]+)"', html)
    return m.group(1) if m else ""


def query(opener, name, trade, token, retries=5, delay=2.4):
    """返回 (code, checkResult列表, 新token)"""
    for _ in range(retries):
        data = urllib.parse.urlencode({
            "pNameDistinct": "",
            "pNameSymbol": name,
            "pNameTrade": trade,
            "token": token,
        }).encode()
        req = urllib.request.Request(API, data=data)
        try:
            raw = opener.open(req, timeout=40).read().decode("utf-8", "ignore")
        except Exception:
            time.sleep(5)
            continue
        if '"code":"500"' in raw:  # 限流
            time.sleep(6)
            token = get_token(opener)
            time.sleep(3)
            continue
        try:
            d = json.loads(raw)
        except Exception:
            time.sleep(3)
            continue
        result = d.get("result", {}).get("NAME_LIST", {})
        items = result.get("checkResult", [])
        return d.get("code"), items if isinstance(items, list) else [], d.get("token", token)
    return "ERR", [], token


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*", help="字号列表")
    ap.add_argument("--file", help="从文件读字号，每行一个")
    ap.add_argument("--trade", default="科技", help="行业，默认科技")
    ap.add_argument("--out", default="national_result.json")
    ap.add_argument("--delay", type=float, default=2.4)
    args = ap.parse_args()

    names = list(args.names)
    if args.file:
        names += [l.strip() for l in open(args.file, encoding="utf-8") if l.strip()]
    if not names:
        ap.error("至少给一个字号，或用 --file")

    opener = make_opener()
    token = get_token(opener)
    time.sleep(2)
    print(f"token={token[:12]}... 共 {len(names)} 个", flush=True)

    results = {}
    for i, n in enumerate(names, 1):
        code, items, token = query(opener, n, args.trade, token)
        hits = len(items)
        mark = "OK 无近似" if code == "200" and hits == 0 else (
            f"WARN {hits}条近似" if code == "200" else f"ERROR {code}")
        print(f"[{i}/{len(names)}] {n}: {mark}", flush=True)
        for it in items[:3]:
            print("    " + str(it)[:160], flush=True)
        results[n] = {"code": code, "totalNum": hits, "nameList": items}
        json.dump(results, open(args.out, "w"), ensure_ascii=False, indent=1)
        time.sleep(args.delay)

    print(f"完成，结果写入 {args.out}", flush=True)


if __name__ == "__main__":
    main()
