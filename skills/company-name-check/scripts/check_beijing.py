#!/usr/bin/env python3
"""北京 e 窗通 · 名称开放查询（复用已登录 Chrome profile）

准备：
  1) 一份已登录 e 窗通 / 北京市政务服务网的 Chrome profile
     - 可直接指定日常 Chrome 的 user_data_dir
     - 也可复制任意内嵌浏览器（Electron / Mini App）的分区目录，
       整理成 <profile>/Default/ 结构后使用
  2) pip install playwright pillow；本机需有 Chrome 与 tesseract

用法:
    python3 check_beijing.py 蓝穹星汉 蓝穹星曜 --profile /tmp/ect-chrome --trade 科技
"""
import argparse
import io
import json
import os
import re
import subprocess
import tempfile
import time
from collections import Counter

from PIL import Image, ImageFilter
from playwright.sync_api import sync_playwright

BASE = "https://ect.scjgj.beijing.gov.cn"
IMG = BASE + "/wsdj/mckf/system/getVerifyCode.do"
API = BASE + "/wsdj/mckf/es/getList.do"
TESS = os.environ.get("TESSERACT_BIN", "/opt/homebrew/bin/tesseract")


def ocr_candidates(path):
    """返回去重后的算式字符串候选"""
    img = Image.open(path).convert("L")
    w, h = img.size
    seen, out = set(), []
    for scale in (6, 10, 12):
        big = img.resize((w * scale, h * scale), Image.LANCZOS)
        for th in (None, 110, 130, 150, 170, 190):
            im = big if th is None else big.point(lambda x, t=th: 0 if x < t else 255)
            im = im.filter(ImageFilter.MedianFilter(3))
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            im.save(tmp.name)
            for psm in ("7", "8", "13"):
                try:
                    o = subprocess.run(
                        [TESS, tmp.name, "-", "--psm", psm, "-c",
                         "tessedit_char_whitelist=0123456789+-xX*/=? "],
                        capture_output=True, text=True, timeout=8).stdout
                except Exception:
                    o = ""
                s = re.sub(r"[^0-9+\-xX*/]", "", o).strip()
                if s and s not in seen:
                    seen.add(s)
                    out.append(s)
            os.unlink(tmp.name)
    return out


def solve(expr):
    e = expr.replace("x", "*").replace("X", "*")
    m = re.fullmatch(r"(\d{1,3})([+\-*/])(\d{1,3})", e)
    if not m:
        return None
    a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
    return {"+": a + b, "-": a - b, "*": a * b,
            "/": (a // b if b and a % b == 0 else None)}[op]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--file")
    ap.add_argument("--profile", required=True, help="已登录的 Chrome user_data_dir")
    ap.add_argument("--trade", default="科技")
    ap.add_argument("--out", default="beijing_result.json")
    ap.add_argument("--rounds", type=int, default=15, help="单个名字最多重试轮数")
    args = ap.parse_args()

    names = list(args.names)
    if args.file:
        names += [l.strip() for l in open(args.file, encoding="utf-8") if l.strip()]
    if not names:
        ap.error("至少给一个字号，或用 --file")

    results = {}
    if os.path.exists(args.out):
        try:
            results = json.load(open(args.out))
        except Exception:
            results = {}

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=args.profile, channel="chrome", headless=True,
            args=["--no-first-run", "--no-default-browser-check"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(BASE + "/wsdj/mckf/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(600)

        for idx, name in enumerate(names, 1):
            if results.get(name, {}).get("status") == "ok":
                print(f"[{idx}/{len(names)}] SKIP {name}", flush=True)
                continue
            done = False
            for cyc in range(1, args.rounds + 1):
                r = ctx.request.get(f"{IMG}?t={os.urandom(4).hex()}", timeout=20000)
                if r.status != 200:
                    time.sleep(1)
                    continue
                tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                tmp.write(r.body())
                tmp.close()
                answers = []
                for c in ocr_candidates(tmp.name):
                    v = solve(c)
                    if v is not None and v not in answers:
                        answers.append(v)
                os.unlink(tmp.name)
                if not answers:
                    continue
                ans = Counter(answers).most_common(1)[0][0]
                body = page.evaluate("""async (a) => {
                    const b = new URLSearchParams({entTra:a.ent, nameInd:a.trade, category:'',
                      verifyCode:String(a.code), pageNum:'', pageSize:''});
                    const r = await fetch(a.url, {method:'POST', body:b,
                      headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8',
                               'X-Requested-With':'XMLHttpRequest'}});
                    return await r.text();
                }""", {"ent": name, "trade": args.trade, "code": ans, "url": API})
                try:
                    d = json.loads(body)
                except Exception:
                    continue
                if d.get("code") == "0000":
                    results[name] = {"status": "ok", "totalNum": d.get("totalNum", 0),
                                     "nameList": d.get("nameList", []), "tries": cyc,
                                     "answer": ans}
                    print(f"[{idx}/{len(names)}] OK {name}: totalNum={d.get('totalNum')} "
                          f"(第{cyc}次)", flush=True)
                    done = True
                    break
                time.sleep(0.4)
            if not done:
                results[name] = {"status": "fail"}
                print(f"[{idx}/{len(names)}] FAIL {name}", flush=True)
            json.dump(results, open(args.out, "w"), ensure_ascii=False, indent=1)

        ctx.close()
    print(f"完成，结果写入 {args.out}", flush=True)


if __name__ == "__main__":
    main()
