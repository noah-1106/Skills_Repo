#!/usr/bin/env python3
"""品牌 / 知识产权重名扫描（本地词库 + 同音互斥提示）

说明：本地词库只做「已知强品牌」拦截，不能替代商标检索。
最终仍需：1) 权利人内部商标库 2) 中国商标网按类检索。

用法:
    python3 brand_scan.py 蓝穹星汉 星环纪 蓝宇星穹
    python3 brand_scan.py --json 全量核验.json
    python3 brand_scan.py --file names.txt
"""
import argparse
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
WATCH = os.path.join(HERE, "..", "references", "brand-watch.json")


def load_watch():
    with open(WATCH, encoding="utf-8") as f:
        return json.load(f)


def scan(names, watch):
    terms = watch["terms"]
    groups = watch.get("homophone_groups", [])
    out = {}
    for n in names:
        hits = [t for t in terms if t["term"] in n]
        homo = []
        for g in groups:
            used = [c for c in g if c in n]
            if used:
                homo.append({"chars": used, "group": g})
        risk = "none"
        if any(h["risk"] == "高" for h in hits):
            risk = "high"
        elif hits:
            risk = "medium"
        out[n] = {
            "brand_hits": [{"term": h["term"], "owner": h["owner"],
                            "evidence": h["evidence"], "risk": h["risk"]} for h in hits],
            "homophone": homo,
            "ip_risk": risk,
            "action": ("需内部商标确认" if any(h["risk"] == "内部" for h in hits)
                       else "需商标检索/回避" if risk in ("high", "medium")
                       else "低（仍需终检）"),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--file", help="每行一个字号")
    ap.add_argument("--json", help="读取核验结果 JSON，取其 key 作为字号")
    ap.add_argument("--out", default="brand_scan.json")
    args = ap.parse_args()

    names = list(args.names)
    if args.file:
        names += [l.strip() for l in open(args.file, encoding="utf-8") if l.strip()]
    if args.json:
        names += list(json.load(open(args.json, encoding="utf-8")).keys())
    names = list(dict.fromkeys(names))
    if not names:
        ap.error("没有输入字号")

    watch = load_watch()
    res = scan(names, watch)

    high = {k: v for k, v in res.items()
            if any(h["risk"] == "高" for h in v["brand_hits"])}
    inner = {k: v for k, v in res.items()
             if not (k in high) and any(h["risk"] == "内部" for h in v["brand_hits"])}
    mid = {k: v for k, v in res.items()
           if not (k in high or k in inner) and v["brand_hits"]}

    print(f"共 {len(names)} 个｜高置信 {len(high)}｜集团内部 {len(inner)}｜通用词需核 {len(mid)}\n")

    def show(title, bucket, icon, tail):
        if not bucket:
            return
        print(f"【{title}】{icon} {tail}")
        for n, v in sorted(bucket.items()):
            terms = "、".join(f"{h['term']}→{h['owner']}" for h in v["brand_hits"])
            print(f"  {icon} {n}: {terms}")
        print()

    show("高置信品牌冲突（建议回避或取得授权）", high, "🚩", "")
    show("集团自有商标（需走内部授权确认）", inner, "🔐", "")
    show("通用词命中（按类别检索后再定，不必然冲突）", mid, "⚠️", "")

    # 同音组：按组统计，提示"同批只能留一个"
    risky = {("辰", "宸", "晨"): "chén", ("宇", "屿", "羽"): "yǔ"}
    for group, py in risky.items():
        members = [n for n in names if any(c in n for c in group)]
        if not members:
            continue
        print(f"【同音互斥】{'/'.join(group)}（{py}）：{len(members)} 个 → 同批只能留一个")
        for i in range(0, len(members), 5):
            print("  · " + " · ".join(members[i:i + 5]))
        print()

    json.dump(res, open(args.out, "w"), ensure_ascii=False, indent=1)
    print(f"结果写入 {args.out}")


if __name__ == "__main__":
    main()
