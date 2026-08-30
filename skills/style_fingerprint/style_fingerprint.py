#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Style Fingerprint v2.0 - Chinese Writing Style Analyzer (zero dependencies)

v2.0 changelog (vs v1.0):
  [FIX] rhetorical_question regex was inverted (always returned 0)
  [FIX] passive_voice false positives on 由于/自由
  [FIX] ellipsis_subject char-class splitting multi-char words
  [FIX] simile false positives on adverbial 好像/似乎
  [REWRITE] lexical layer: sliding-window pseudo-tokenizer -> closed-set
            function-word fingerprints (closed sets need no tokenizer)
  [ADD] compare: new text vs fingerprint deviation report (writing loop)
  [ADD] merge: combine multiple fingerprints (char-count weighted)
  [ADD] selftest: built-in regression cases
  [ADD] exemplar sentence extraction (few-shot for writing agents)
  [ADD] low_confidence flag for small samples (<300 chars)
  [KEEP] fingerprints stored inside skill dir (product decision, v1 behavior)
"""

import sys
import re
import json
import argparse
from datetime import datetime
from pathlib import Path

# ---------- output safety for Windows GBK consoles ----------
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SKILL_DIR = Path(__file__).parent.resolve()
FINGERPRINTS_DIR = SKILL_DIR / "fingerprints"
FINGERPRINTS_DIR.mkdir(exist_ok=True)  # v1 behavior kept by product decision

FP_VERSION = "2.0"

# ============================================================
# Closed-set word lists (the core of v2 lexical layer)
# Rationale: personal style shows up most strongly in function
# words & catchphrases, which are enumerable closed sets.
# No tokenizer needed -> zero dependencies preserved.
# ============================================================

STOPWORDS = set(list("的了在是我有和就不人都一上个也很到说要去你会着没有好自己这那们来个吗吧啊呢哦嗯为之与及等或但而因于以被把让给向往从到在当比跟同对"))

QUESTION_WORDS = [
    "为什么", "怎么", "怎样", "如何", "什么", "哪里", "哪个", "哪些", "谁",
    "难道", "岂", "怎能", "怎么会", "是否", "能否", "可否", "何时", "多少",
]
CONJUNCTION_WORDS = [
    "但是", "然而", "不过", "可是", "因此", "所以", "于是", "然后", "接着",
    "其实", "当然", "总之", "首先", "其次", "最后", "另外", "此外", "而且",
    "并且", "虽然", "尽管", "如果", "假如", "要是", "只要", "除非", "无论",
    "不管", "既然", "因为", "由于", "因而", "从而", "甚至", "何况", "况且",
    "反之", "相反", "同时", "与此同时", "事实上", "实际上", "换句话说",
]
MODALITY_WORDS = [
    "可能", "也许", "大概", "应该", "必须", "一定", "肯定", "似乎", "好像",
    "或许", "恐怕", "显然", "确实", "真的", "未必", "无疑", "势必", "兴许",
]
DEGREE_WORDS = [
    "非常", "特别", "十分", "极其", "尤其", "更", "最", "太", "挺", "蛮",
    "超", "相当", "格外", "极为", "万分", "尤为", "颇", "略微", "稍微",
    "有点", "有些", "极",
]
PERSON_MULTI = ["我们", "你们", "他们", "她们", "它们", "大家", "咱们", "人家", "自己", "本人"]
PERSON_SINGLE = ["我", "你", "您", "他", "她", "它", "咱"]
TONE_PARTICLES = ["呢", "吧", "啊", "嘛", "啦", "哦", "哟", "呀", "呗", "喽", "嘿", "哈", "唉", "哎", "嗯", "哼", "哇", "咯"]

# phrases that would falsely read as ellipsis-subject openers
SENTENCE_OPENERS_NO_SUBJECT = re.compile(
    r"^(?:[\u4e00-\u9fa5]着|[\u4e00-\u9fa5]了起来|"
    r"感到|觉得|发现|看见|听见|闻到|想到|想起|意识到|明白|突然|终于|"
    r"是|有|让|使)"
)

# v2 simile: require simile-marker + following char; exclude adverbial 好像
SIMILE_PATTERN = re.compile(r"(?:(?<!好)像|仿佛|如同|宛如|犹如|好似|恰似|酷似|好比)[\u4e00-\u9fa5]")
# v2 passive: 被-clause with noun-noun guard, plus explicit receive-verbs, plus 为...所...
PASSIVE_PATTERNS = [
    re.compile(r"[\u4e00-\u9fa5]{1,3}被(?!子|套|单|褥|胎)[\u4e00-\u9fa5]{1,5}"),
    re.compile(r"(?:受到|遭受|遭到)[\u4e00-\u9fa5]{2,4}"),
    re.compile(r"为[\u4e00-\u9fa5]{1,4}所[\u4e00-\u9fa5]{1,3}"),
]
RHETORIC_MARKERS = re.compile(r"(?:难道|岂|怎能|哪能|怎么能|怎么会|怎么说|何必|何苦|何尝|哪里是|谁说)")
LONG_ATTRIBUTIVE = re.compile(r"的[^。！？，,、\n]{4,}的")

SENSORY_LEXICON = {
    "visual": ["看见", "看到", "望着", "瞧", "瞥", "盯", "瞪", "光", "影", "颜色",
               "色彩", "暗", "黑色", "白色", "红色", "蓝色", "绿色", "灰色", "形状"],
    "auditory": ["听见", "听到", "声音", "响声", "喧闹", "寂静", "安静", "吵闹",
                 "旋律", "音乐", "歌声", "朗读", "听"],
    "tactile": ["摸到", "触摸", "碰触", "温度", "温暖", "冰凉", "粗糙", "光滑",
                "柔软", "坚硬", "潮湿", "干燥", "疼痛", "发痒", "发麻", "触感"],
    "olfactory_gustatory": ["闻到", "嗅到", "芳香", "清香", "香味", "臭味", "味道",
                            "气味", "酸甜", "苦涩", "咸味", "入口", "回甘"],
}
SENSORY_LABELS = {"visual": "视觉", "auditory": "听觉", "tactile": "触觉",
                  "olfactory_gustatory": "嗅味觉"}

MIN_CONFIDENT_CHARS = 300  # below this -> low_confidence=true


def _split_sentences(text: str):
    """保留句尾标点（句式判断需要知道问句），统计句长时再剥离。"""
    parts = re.findall(r"[^。！？!?；;\n]+[。！？!?；;\n]?", text)
    return [p.strip() for p in parts if p.strip()]


def _strip_tail_punct(s: str) -> str:
    return re.sub(r"[。！？!?；;，,、]+$", "", s).strip()


def _count_non_overlapping(text: str, words) -> int:
    total = 0
    for w in sorted(words, key=len, reverse=True):  # longest first
        total += text.count(w)
        text = text.replace(w, " " * len(w))  # blank out to avoid sub-counting
    return total


def _find_phrase_counts(text: str, words) -> dict:
    counts = {}
    remaining = text
    for w in sorted(words, key=len, reverse=True):
        c = remaining.count(w)
        if c > 0:
            counts[w] = c
            remaining = remaining.replace(w, " " * len(w))
    return counts


def _extract_ngrams(sentences, n: int):
    grams = {}
    for s in sentences:
        han = re.findall(r"[\u4e00-\u9fa5]+", s)
        for run in han:
            if len(run) < n:
                continue
            for i in range(len(run) - n + 1):
                g = run[i:i + n]
                grams[g] = grams.get(g, 0) + 1
    return grams


def _extract_exemplars(text, sentences, stats) -> list:
    """Pick representative sentences for few-shot: first, last, closest-to-avg,
    plus any sentence carrying simile or rhetorical question."""
    picked = []
    seen = set()

    def add(s):
        if s and s not in seen and len(s) <= 60:
            seen.add(s)
            picked.append(s)

    if not sentences:
        return []
    add(sentences[0])
    if len(sentences) > 1:
        add(sentences[-1])
    if stats["sentence_count"] > 0:
        avg = stats["avg_sentence_length"]
        cand = min(sentences, key=lambda s: abs(len(s) - avg))
        add(cand)
    for s in sentences:
        if SIMILE_PATTERN.search(s) or RHETORIC_MARKERS.search(s):
            add(s)
        if len(picked) >= 5:
            break
    return picked[:5]


class StyleAnalyzer:
    """All metrics normalized: patterns per 100 sentences, words per 1000 chars."""

    def analyze(self, text: str) -> dict:
        text = text.strip()
        sentences = _split_sentences(text)
        n_sent = len(sentences)
        n_chars = len(re.findall(r"[\u4e00-\u9fa5]", text))

        # ---- rhythm ----
        sent_lens = [len(_strip_tail_punct(s)) for s in sentences]
        avg_len = round(sum(sent_lens) / n_sent, 1) if n_sent else 0
        short = sum(1 for l in sent_lens if l <= 15)
        medium = sum(1 for l in sent_lens if 15 < l <= 28)
        long_ = sum(1 for l in sent_lens if l > 28)
        dist = {"short_pct": round(short * 100 / n_sent, 1) if n_sent else 0,
                "medium_pct": round(medium * 100 / n_sent, 1) if n_sent else 0,
                "long_pct": round(long_ * 100 / n_sent, 1) if n_sent else 0}
        comma_n = text.count("，") + text.count(",")
        comma_density = round(comma_n / n_sent, 2) if n_sent else 0
        per1000 = (lambda c: round(c * 1000 / n_chars, 2)) if n_chars else (lambda c: 0)
        rhythm = {
            "avg_sentence_length": avg_len,
            "sentence_length_distribution": dist,
            "comma_density_per_sentence": comma_density,
            "exclamation_per_1000": per1000(text.count("！") + text.count("!")),
            "question_per_1000": per1000(text.count("？") + text.count("?")),
            "ellipsis_per_1000": per1000(text.count("……") + text.count("...")),
            "dash_per_1000": per1000(text.count("——") + text.count("—")),
        }

        # ---- syntax patterns (per 100 sentences) ----
        rhetorical = sum(1 for s in sentences
                         if RHETORIC_MARKERS.search(s) and re.search(r"[？?]\s*$", s))
        passive = sum(1 for s in sentences if any(p.search(s) for p in PASSIVE_PATTERNS))
        ellipsis = sum(1 for s in sentences if SENTENCE_OPENERS_NO_SUBJECT.match(s))
        attr_long = sum(1 for s in sentences if LONG_ATTRIBUTIVE.search(s))
        simile_n = sum(1 for s in sentences if SIMILE_PATTERN.search(s))
        per100 = (lambda c: round(c * 100 / n_sent, 1)) if n_sent else (lambda c: 0.0)
        patterns = {
            "rhetorical_question": per100(rhetorical),
            "passive_voice": per100(passive),
            "ellipsis_subject": per100(ellipsis),
            "long_attributive": per100(attr_long),
            "simile": per100(simile_n),
        }

        # ---- lexical: closed-set function words (per 1000 chars) ----
        fw = {
            "question_words": _find_phrase_counts(text, QUESTION_WORDS),
            "conjunctions": _find_phrase_counts(text, CONJUNCTION_WORDS),
            "modality": _find_phrase_counts(text, MODALITY_WORDS),
            "degree": _find_phrase_counts(text, DEGREE_WORDS),
            "tone_particles": _find_phrase_counts(text, TONE_PARTICLES),
        }
        person_counts = _find_phrase_counts(text, PERSON_MULTI + PERSON_SINGLE)
        person = {
            "first_person": person_counts.get("我", 0) + person_counts.get("我们", 0) + person_counts.get("咱", 0) + person_counts.get("咱们", 0),
            "second_person": person_counts.get("你", 0) + person_counts.get("您", 0) + person_counts.get("你们", 0),
            "third_person": person_counts.get("他", 0) + person_counts.get("她", 0) + person_counts.get("它", 0) + person_counts.get("他们", 0) + person_counts.get("她们", 0),
            "collective": person_counts.get("大家", 0) + person_counts.get("人家", 0) + person_counts.get("自己", 0),
        }
        lexical = {
            "category_totals_per_1000": {
                k: per1000(sum(v.values())) for k, v in fw.items()
            },
            "person_per_1000": {k: per1000(v) for k, v in person.items()},
            "top_function_words": {},
        }
        merged = {}
        for v in fw.values():
            for w, c in v.items():
                merged[w] = merged.get(w, 0) + c
        lexical["top_function_words"] = dict(sorted(merged.items(), key=lambda x: -x[1])[:10])

        # ---- catchphrase candidates: 3-grams repeating across >=2 sentences ----
        sents_with = set()
        grams = {}
        for s in sentences:
            local = set()
            for run in re.findall(r"[\u4e00-\u9fa5]+", s):
                for i in range(len(run) - 2):
                    g = run[i:i + 3]
                    local.add(g)
                    grams[g] = grams.get(g, 0) + 1
            for g in local:
                sents_with.add(g)
        # count sentences containing each gram
        gram_sent_count = {}
        for s in sentences:
            seen_local = set()
            for run in re.findall(r"[\u4e00-\u9fa5]+", s):
                for i in range(len(run) - 2):
                    g = run[i:i + 3]
                    if g not in seen_local:
                        seen_local.add(g)
                        gram_sent_count[g] = gram_sent_count.get(g, 0) + 1
        candidates = []
        for g, sent_n in gram_sent_count.items():
            if sent_n >= 2:
                # skip grams made entirely of stopwords
                if all(ch in STOPWORDS for ch in g):
                    continue
                candidates.append({"phrase": g, "sentences": sent_n})
        candidates.sort(key=lambda x: (-x["sentences"], x["phrase"]))
        lexical["catchphrase_candidates"] = candidates[:8]

        # ---- sensory (per 1000 chars) ----
        sensory_counts = {}
        for cat, words in SENSORY_LEXICON.items():
            sensory_counts[cat] = _count_non_overlapping(text, words)
        dominant_cat = max(sensory_counts, key=sensory_counts.get) if any(sensory_counts.values()) else None
        sensory = {
            "dominant": SENSORY_LABELS.get(dominant_cat, "无") if dominant_cat else "无",
            "per_1000": {cat: per1000(c) for cat, c in sensory_counts.items()},
        }

        # ---- exemplars & confidence ----
        stats = {"sentence_count": n_sent, "avg_sentence_length": avg_len}
        exemplars = _extract_exemplars(text, sentences, stats)

        return {
            "version": FP_VERSION,
            "sample": {
                "char_count": n_chars,
                "sentence_count": n_sent,
                "low_confidence": n_chars < MIN_CONFIDENT_CHARS,
                "source_text_sample": text[:500],
            },
            "rhythm": rhythm,
            "syntax_preference": {"patterns_per_100_sentences": patterns},
            "lexical": lexical,
            "sensory": sensory,
            "exemplar_sentences": exemplars,
        }


# ============================================================
# storage (skill dir, per product decision)
# ============================================================

def _fp_path(name: str) -> Path:
    safe = name.replace("/", "_").replace("\\", "_")
    return FINGERPRINTS_DIR / f"{safe}.json"


def save_fingerprint(name: str, fp: dict) -> Path:
    path = _fp_path(name)
    path.write_text(json.dumps(fp, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_fingerprint(name: str) -> dict:
    path = _fp_path(name)
    if not path.exists():
        raise FileNotFoundError(f"指纹不存在: {name} (查找 {path})")
    return json.loads(path.read_text(encoding="utf-8"))


def list_fingerprints() -> list:
    return sorted(FINGERPRINTS_DIR.glob("*.json"))


def delete_fingerprint(name: str) -> bool:
    path = _fp_path(name)
    if path.exists():
        path.unlink()
        return True
    return False


# ============================================================
# compare: new text vs fingerprint  (the writing loop)
# ============================================================

WARN_DEV = 0.30   # |deviation| beyond 30% -> warn
FAIL_DEV = 0.60   # beyond 60% -> fail


def _dev_status(base: float, new: float, neutral_zero: bool = True):
    if base == 0 and new == 0:
        if neutral_zero:
            return "ok", 0.0, "两边都未出现，一致"
        return "info", 0.0, "两边都未出现——信息不足，不算一致证据"
    if base == 0:
        return "info", None, f"指纹样本中未出现（本次 {new}），确认是否符合该作者习惯"
    dev = (new - base) / base
    if abs(dev) <= WARN_DEV:
        return "ok", dev, "偏差在容差内"
    if abs(dev) <= FAIL_DEV:
        if dev > 0:
            return "warn", dev, f"比指纹高 {abs(dev)*100:.0f}%，考虑收敛"
        return "warn", dev, f"比指纹低 {abs(dev)*100:.0f}%，考虑补足"
    if dev > 0:
        return "fail", dev, f"远高于指纹 (+{abs(dev)*100:.0f}%)，明显偏离该作者风格"
    return "fail", dev, f"远低于指纹 (-{abs(dev)*100:.0f}%)，明显偏离该作者风格"


def compare_fingerprint(fp: dict, text: str) -> dict:
    analyzer = StyleAnalyzer()
    new = analyzer.analyze(text)
    rows = []

    base_r = fp.get("rhythm", {})
    new_r = new["rhythm"]
    for key, label in [("avg_sentence_length", "平均句长(字)"),
                       ("comma_density_per_sentence", "逗号密度(每句)")]:
        st, dev, msg = _dev_status(base_r.get(key, 0), new_r.get(key, 0))
        rows.append({"dim": label, "base": base_r.get(key, 0),
                     "new": new_r.get(key, 0), "status": st, "dev": dev, "msg": msg})

    base_p = fp.get("syntax_preference", {}).get("patterns_per_100_sentences", {})
    new_p = new["syntax_preference"]["patterns_per_100_sentences"]
    plabels = {"rhetorical_question": "反问句", "passive_voice": "被动句",
               "ellipsis_subject": "省略主语", "long_attributive": "长定语",
               "simile": "明喻"}
    for k, label in plabels.items():
        st, dev, msg = _dev_status(base_p.get(k, 0), new_p.get(k, 0))
        rows.append({"dim": f"{label}(每百句)", "base": base_p.get(k, 0),
                     "new": new_p.get(k, 0), "status": st, "dev": dev, "msg": msg})

    base_l = fp.get("lexical", {}).get("category_totals_per_1000", {})
    new_l = new["lexical"]["category_totals_per_1000"]
    llabels = {"question_words": "疑问词", "conjunctions": "连接词",
               "modality": "情态词", "degree": "程度词", "tone_particles": "语气词"}
    for k, label in llabels.items():
        st, dev, msg = _dev_status(base_l.get(k, 0), new_l.get(k, 0), neutral_zero=False)
        rows.append({"dim": f"{label}(每千字)", "base": base_l.get(k, 0),
                     "new": new_l.get(k, 0), "status": st, "dev": dev, "msg": msg})

    base_sp = fp.get("lexical", {}).get("person_per_1000", {})
    new_sp = new["lexical"]["person_per_1000"]
    splabels = {"first_person": "第一人称", "second_person": "第二人称",
                "third_person": "第三人称"}
    for k, label in splabels.items():
        st, dev, msg = _dev_status(base_sp.get(k, 0), new_sp.get(k, 0), neutral_zero=False)
        rows.append({"dim": f"{label}(每千字)", "base": base_sp.get(k, 0),
                     "new": new_sp.get(k, 0), "status": st, "dev": dev, "msg": msg})

    if fp.get("sample", {}).get("low_confidence"):
        for r in rows:
            if r["status"] == "fail":
                r["status"] = "warn"
                r["msg"] += "（指纹基线为小样本，降级提示）"

    n_ok = sum(1 for r in rows if r["status"] == "ok")
    n_info = sum(1 for r in rows if r["status"] == "info")
    n_warn = sum(1 for r in rows if r["status"] == "warn")
    n_fail = sum(1 for r in rows if r["status"] == "fail")
    score = round(n_ok * 100 / len(rows), 0) if rows else 0

    return {
        "fingerprint": fp.get("name", "?"),
        "rows": rows,
        "summary": {"pass": n_ok, "info": n_info, "warn": n_warn,
                    "fail": n_fail, "total": len(rows), "score": score},
        "new_sample": new["sample"],
    }


# ============================================================
# merge: combine fingerprints weighted by char count
# ============================================================

def merge_fingerprints(names: list, out_name: str) -> dict:
    fps = [load_fingerprint(n) for n in names]
    total_chars = sum(f["sample"]["char_count"] for f in fps)
    if total_chars == 0:
        raise ValueError("所有样本字数为 0，无法合并")

    def wavg(getter):
        acc, wsum = 0.0, 0.0
        for f in fps:
            w = f["sample"]["char_count"]
            v = getter(f)
            if v is None:
                continue
            acc += v * w
            wsum += w
        return round(acc / wsum, 2) if wsum else 0

    merged = {
        "version": FP_VERSION,
        "name": out_name,
        "merged_from": names,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "sample": {
            "char_count": total_chars,
            "sentence_count": sum(f["sample"]["sentence_count"] for f in fps),
            "low_confidence": total_chars < MIN_CONFIDENT_CHARS,
            "source_text_sample": fps[0]["sample"].get("source_text_sample", ""),
        },
        "rhythm": {
            "avg_sentence_length": wavg(lambda f: f["rhythm"].get("avg_sentence_length")),
            "sentence_length_distribution": {
                k: wavg(lambda f, k=k: f["rhythm"]["sentence_length_distribution"].get(k))
                for k in ["short_pct", "medium_pct", "long_pct"]
            },
            "comma_density_per_sentence": wavg(lambda f: f["rhythm"].get("comma_density_per_sentence")),
            "exclamation_per_1000": wavg(lambda f: f["rhythm"].get("exclamation_per_1000")),
            "question_per_1000": wavg(lambda f: f["rhythm"].get("question_per_1000")),
            "ellipsis_per_1000": wavg(lambda f: f["rhythm"].get("ellipsis_per_1000")),
            "dash_per_1000": wavg(lambda f: f["rhythm"].get("dash_per_1000")),
        },
    }

    pat_keys = ["rhetorical_question", "passive_voice", "ellipsis_subject",
                "long_attributive", "simile"]
    merged["syntax_preference"] = {"patterns_per_100_sentences": {
        k: wavg(lambda f, k=k: f.get("syntax_preference", {})
                .get("patterns_per_100_sentences", {}).get(k)) for k in pat_keys}}

    cat_keys = ["question_words", "conjunctions", "modality", "degree", "tone_particles"]
    merged["lexical"] = {
        "category_totals_per_1000": {
            k: wavg(lambda f, k=k: f.get("lexical", {})
                    .get("category_totals_per_1000", {}).get(k)) for k in cat_keys},
        "person_per_1000": {
            k: wavg(lambda f, k=k: f.get("lexical", {})
                    .get("person_per_1000", {}).get(k))
            for k in ["first_person", "second_person", "third_person", "collective"]},
        "top_function_words": {},
        "catchphrase_candidates": [],
    }
    # union catchphrases with weighted sentence counts
    cp = {}
    for f in fps:
        w = f["sample"]["char_count"] / total_chars
        for item in f.get("lexical", {}).get("catchphrase_candidates", []):
            cp[item["phrase"]] = cp.get(item["phrase"], 0) + item["sentences"] * w
    merged["lexical"]["catchphrase_candidates"] = [
        {"phrase": k, "sentences": round(v, 1)}
        for k, v in sorted(cp.items(), key=lambda x: -x[1])[:8]
    ]
    # union top function words by weighted count
    tfw = {}
    for f in fps:
        w = f["sample"]["char_count"]
        for word, c in f.get("lexical", {}).get("top_function_words", {}).items():
            tfw[word] = tfw.get(word, 0) + c
    merged["lexical"]["top_function_words"] = dict(
        sorted(tfw.items(), key=lambda x: -x[1])[:10])

    # sensory: weighted average of per-1000, dominant = max
    skeys = list(SENSORY_LEXICON.keys())
    sensory_per = {k: wavg(lambda f, k=k: f.get("sensory", {})
                           .get("per_1000", {}).get(k)) for k in skeys}
    dom = max(sensory_per, key=sensory_per.get) if any(v > 0 for v in sensory_per.values()) else None
    merged["sensory"] = {
        "dominant": SENSORY_LABELS.get(dom, "无") if dom else "无",
        "per_1000": sensory_per,
    }

    # exemplars: up to 2 from each source
    ex = []
    for f in fps:
        ex.extend(f.get("exemplar_sentences", [])[:2])
    seen = set()
    uniq = []
    for s in ex:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    merged["exemplar_sentences"] = uniq[:6]
    return merged


# ============================================================
# export: rules + exemplars (few-shot beats rules alone)
# ============================================================

def _rhythm_guide(fp: dict) -> list:
    r = fp["rhythm"]
    avg = r["avg_sentence_length"]
    dist = r["sentence_length_distribution"]
    out = []
    if avg <= 18:
        out.append(f"多用短句（作者平均句长 {avg} 字），保持节奏与冲击力")
    elif avg >= 28:
        out.append(f"可用较长句（作者平均句长 {avg} 字），铺陈细节与逻辑链")
    else:
        out.append(f"长短句结合（作者平均句长 {avg} 字），避免单一节奏")
    if dist["short_pct"] >= 50:
        out.append(f"短句（≤15字）占比 {dist['short_pct']}%——穿插长句时保持整体短促基调")
    if r.get("dash_per_1000", 0) >= 1:
        out.append("作者习惯用破折号——可沿用制造停顿与转折")
    if r.get("ellipsis_per_1000", 0) >= 1:
        out.append("作者习惯用省略号制造留白与余韵")
    return out


def _lexical_guide(fp: dict) -> list:
    l = fp["lexical"]
    out = []
    p = l.get("person_per_1000", {})
    if p.get("first_person", 0) >= 8:
        out.append(f"第一人称高频（每千字 {p['first_person']} 次）——保持『我』的视角在场感")
    if p.get("second_person", 0) >= 8:
        out.append(f"对读者直呼『你』（每千字 {p['second_person']} 次）——保持对话感")
    if l.get("category_totals_per_1000", {}).get("tone_particles", 0) >= 5:
        out.append("语气词密度高——口语感是作者标志，不要写成书面腔")
    cps = l.get("catchphrase_candidates", [])
    if cps:
        phrases = "、".join(c["phrase"] for c in cps[:3])
        out.append(f"重复短语候选（可能是口头禅）：{phrases}——可适度沿用")
    return out


def _pattern_guide(fp: dict) -> list:
    p = fp.get("syntax_preference", {}).get("patterns_per_100_sentences", {})
    out = []
    if p.get("rhetorical_question", 0) >= 2:
        out.append(f"善用反问句（每百句 {p['rhetorical_question']} 次）——用于强调观点")
    if p.get("simile", 0) >= 2:
        out.append(f"明喻丰富（每百句 {p['simile']} 次）——用『像/仿佛/如同』式比喻")
    if p.get("passive_voice", 0) >= 2:
        out.append(f"被动句偏多（每百句 {p['passive_voice']} 次）——保持此句式习惯")
    if p.get("ellipsis_subject", 0) >= 3:
        out.append("常省略主语开头——延续动词开头的镜头感")
    if p.get("long_attributive", 0) >= 2:
        out.append("存在长定语句——信息密度高是该作者特征")
    return out


def export_guide(fp: dict) -> str:
    name = fp.get("name", "未命名")
    s = fp["sample"]
    lines = []
    lines.append(f"# 写作风格指南：{name}")
    lines.append("")
    lines.append(f"> 样本 {s['char_count']} 字 / {s['sentence_count']} 句"
                 + ("　⚠️ 样本不足 300 字，结论仅供参考" if s.get("low_confidence") else ""))
    lines.append("")
    lines.append("## 一、硬指标（写作后可用 compare 校验）")
    lines.append("")
    r = fp["rhythm"]
    lines.append(f"- 平均句长：{r['avg_sentence_length']} 字")
    lines.append(f"- 短/中/长句占比：{r['sentence_length_distribution']['short_pct']}% / "
                 f"{r['sentence_length_distribution']['medium_pct']}% / "
                 f"{r['sentence_length_distribution']['long_pct']}%")
    lines.append(f"- 逗号密度：{r['comma_density_per_sentence']} /句")
    p = fp["syntax_preference"]["patterns_per_100_sentences"]
    lines.append(f"- 反问句：{p['rhetorical_question']} /百句　明喻：{p['simile']} /百句")
    lines.append("")
    lines.append("## 二、风格规则")
    lines.append("")
    for item in _rhythm_guide(fp) + _pattern_guide(fp) + _lexical_guide(fp):
        lines.append(f"- {item}")
    lines.append("")
    lines.append("## 三、范例句（模仿这些句子的语感，比规则更重要）")
    lines.append("")
    for i, sent in enumerate(fp.get("exemplar_sentences", []), 1):
        lines.append(f"{i}. 「{sent}」")
    if not fp.get("exemplar_sentences"):
        lines.append("（样本中未抽取到范例句）")
    lines.append("")
    lines.append("## 四、感官偏好")
    lines.append("")
    lines.append(f"- 主导感官：{fp['sensory']['dominant']}")
    lines.append("")
    lines.append("## 五、校验方式")
    lines.append("")
    lines.append("写完后运行：`python3 style_fingerprint.py compare "
                 f"--name {name} --file 新稿.txt`，查看各维度偏差。")
    lines.append("")
    return "\n".join(lines)


# ============================================================
# report rendering
# ============================================================

def print_report(name: str, fp: dict):
    s = fp["sample"]
    r = fp["rhythm"]
    p = fp["syntax_preference"]["patterns_per_100_sentences"]
    lex = fp["lexical"]

    conf = "⚠️ 样本不足，结论仅供参考" if s.get("low_confidence") else "✓"
    print()
    print("╔" + "═" * 56 + "╗")
    print(f"║  【风格指纹 v2】{name[:24]:<24} {conf}")
    print("╚" + "═" * 56 + "╝")
    print()
    print("📊 基础节奏")
    print("─" * 58)
    print(f"• {s['char_count']} 字 / {s['sentence_count']} 句　平均句长 {r['avg_sentence_length']} 字")
    d = r["sentence_length_distribution"]
    print(f"• 短/中/长句：{d['short_pct']}% / {d['medium_pct']}% / {d['long_pct']}%")
    print(f"• 逗号密度 {r['comma_density_per_sentence']}/句　"
          f"感叹 {r['exclamation_per_1000']}/千字　问号 {r['question_per_1000']}/千字")
    print()
    print("🎯 句式指纹（每百句）")
    print("─" * 58)
    print(f"• 反问 {p['rhetorical_question']}　被动 {p['passive_voice']}　"
          f"省略主语 {p['ellipsis_subject']}　长定语 {p['long_attributive']}　明喻 {p['simile']}")
    print()
    print("🔤 功能词指纹（每千字）")
    print("─" * 58)
    ct = lex["category_totals_per_1000"]
    print(f"• 疑问 {ct.get('question_words',0)}　连接 {ct.get('conjunctions',0)}　"
          f"情态 {ct.get('modality',0)}　程度 {ct.get('degree',0)}　语气词 {ct.get('tone_particles',0)}")
    pp = lex["person_per_1000"]
    print(f"• 人称：我 {pp.get('first_person',0)}　你 {pp.get('second_person',0)}　"
          f"他/她 {pp.get('third_person',0)}")
    top = lex.get("top_function_words", {})
    if top:
        tops = ", ".join(f"{k}×{v}" for k, v in list(top.items())[:6])
        print(f"• 高频功能词：{tops}")
    cps = lex.get("catchphrase_candidates", [])
    if cps:
        cps_s = ", ".join(f"{c['phrase']}(跨{c['sentences']}句)" for c in cps[:5])
        print(f"• 口头禅候选：{cps_s}")
    print()
    print("👀 感官偏好")
    print("─" * 58)
    print(f"• 主导：{fp['sensory']['dominant']}　"
          + "　".join(f"{SENSORY_LABELS[k]} {v}/千字" for k, v in fp["sensory"]["per_1000"].items()))
    ex = fp.get("exemplar_sentences", [])
    if ex:
        print()
        print("💬 范例句")
        print("─" * 58)
        for i, sent in enumerate(ex[:3], 1):
            print(f"{i}. 「{sent}」")
    print()


def print_compare(rep: dict):
    print()
    print("╔" + "═" * 56 + "╗")
    print(f"║  【风格校验】vs 指纹：{rep['fingerprint'][:30]}")
    print("╚" + "═" * 56 + "╝")
    icons = {"ok": "✅", "warn": "⚠️ ", "fail": "❌", "info": "ℹ️ "}
    for r in rep["rows"]:
        dev = f" ({r['dev']*100:+.0f}%)" if r["dev"] is not None else ""
        print(f"{icons[r['status']]} {r['dim']}: 指纹 {r['base']} → 本稿 {r['new']}{dev}")
        if r["status"] in ("warn", "fail", "info"):
            print(f"    └ {r['msg']}")
    s = rep["summary"]
    print()
    print(f"合计：✅{s['pass']}  ℹ️{s['info']}  ⚠️{s['warn']}  ❌{s['fail']}"
          f"　一致率 {s['score']:.0f}%")
    if rep.get("new_sample", {}).get("low_confidence"):
        print("⚠️ 本稿不足 300 字，校验结论置信度低")
    print()


# ============================================================
# selftest
# ============================================================

def selftest() -> bool:
    cases = []
    a = StyleAnalyzer()

    def run(text):
        return a.analyze(text)["syntax_preference"]["patterns_per_100_sentences"], \
               a.analyze(text)

    # 1. rhetorical question (v1 bug: always 0)
    pats, _ = run("难道这不是最好的选择吗？你怎么能这样说呢？今天天气很好。")
    ok = pats["rhetorical_question"] >= 66  # 2 of 3 sentences
    cases.append(("反问句检测≥2/3句", ok, pats["rhetorical_question"]))

    # 2. passive true positive
    pats, _ = run("他被老师批评了。案子被警方破了。")
    ok = pats["passive_voice"] >= 100
    cases.append(("被动句检出≥2/2句", ok, pats["passive_voice"]))

    # 3. passive false positive guard (v1 bug: 由于/自由 counted)
    pats, _ = run("由于天气好，我们享受自由。今天阳光灿烂。")
    ok = pats["passive_voice"] == 0
    cases.append(("由于/自由零误伤", ok, pats["passive_voice"]))

    # 4. ellipsis subject true positive
    pats, _ = run("看着窗外，心里很静。感到一阵轻松。")
    ok = pats["ellipsis_subject"] >= 100
    cases.append(("省略主语检出≥2/2句", ok, pats["ellipsis_subject"]))

    # 5. ellipsis false positive guard ("可能"开头不是省略主语)
    pats, _ = run("可能下雨。大概要迟到。")
    ok = pats["ellipsis_subject"] == 0
    cases.append(("可能/大概零误伤", ok, pats["ellipsis_subject"]))

    # 6. simile true positive
    pats, _ = run("他像一只快乐的猴子。湖水宛如一面镜子。")
    ok = pats["simile"] >= 100
    cases.append(("明喻检出≥2/2句", ok, pats["simile"]))

    # 7. simile false positive guard (adverbial 好像)
    pats, _ = run("他好像去过了。似乎要下雨了。")
    ok = pats["simile"] == 0
    cases.append(("好像/似乎零误伤", ok, pats["simile"]))

    # 8. lexical closed-set sanity: conjunction counted
    fp = a.analyze("但是今天很冷。但是我还是去了。")
    ok = fp["lexical"]["category_totals_per_1000"]["conjunctions"] > 0
    cases.append(("连接词计数>0", ok, fp["lexical"]["category_totals_per_1000"]["conjunctions"]))

    # 9. catchphrase candidate detected across sentences
    fp = a.analyze("说实话这个方案不行。我觉得还行。说实话我反对。说实话再见。")
    cps = [c["phrase"] for c in fp["lexical"]["catchphrase_candidates"]]
    ok = "说实话" in cps
    cases.append(("跨句口头禅「说实话」入候选", ok, cps[:3]))

    # 10b. dominant sensory threshold: pure rational text must NOT get a sensory label
    _fp = a.analyze("选型以需求边界为准。能力过剩等于复杂度全担。亮红灯，建议不立项。")
    cases.append(("纯理性文本主导感官=无", _fp["sensory"]["dominant"] == "无", _fp["sensory"]["dominant"]))

    # 10. low confidence flag
    fp = a.analyze("很短。")
    ok = fp["sample"]["low_confidence"] is True
    cases.append(("短样本 low_confidence=true", ok, fp["sample"]["char_count"]))

    print()
    print("=" * 50)
    print("selftest 结果")
    print("=" * 50)
    all_ok = True
    for name, ok, detail in cases:
        mark = "✅" if ok else "❌"
        if not ok:
            all_ok = False
        print(f"{mark} {name}　(detail: {detail})")
    print("=" * 50)
    print("ALL PASS ✅" if all_ok else "FAILED ❌")
    return all_ok


# ============================================================
# CLI
# ============================================================

def cmd_analyze(args):
    if args.text:
        text = args.text
    elif args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"❌ 文件不存在: {args.file}")
            sys.exit(1)
        text = path.read_text(encoding="utf-8", errors="replace")
    else:
        print("❌ 需要 --text 或 --file")
        sys.exit(1)

    fp = StyleAnalyzer().analyze(text)
    fp["name"] = args.name
    fp["created_at"] = datetime.now().isoformat(timespec="seconds")
    path = save_fingerprint(args.name, fp)
    print(f"✓ 已保存指纹: {path}")
    print_report(args.name, fp)
    if fp["sample"]["low_confidence"]:
        print("⚠️ 提示：样本不足 300 字，建议用更长的文本重新 analyze，"
              "或用 merge 合并多篇。\n")


def cmd_compare(args):
    fp = load_fingerprint(args.name)
    if args.text:
        text = args.text
    elif args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"❌ 文件不存在: {args.file}")
            sys.exit(1)
        text = path.read_text(encoding="utf-8", errors="replace")
    else:
        print("❌ 需要 --text 或 --file")
        sys.exit(1)
    rep = compare_fingerprint(fp, text)
    print_compare(rep)


def cmd_merge(args):
    names = [n.strip() for n in args.names.split(",") if n.strip()]
    if len(names) < 2:
        print("❌ merge 需要 ≥2 个指纹：--names a,b,c")
        sys.exit(1)
    missing = [n for n in names if not _fp_path(n).exists()]
    if missing:
        print(f"❌ 指纹不存在: {', '.join(missing)}（用 list 查看已有指纹）")
        sys.exit(1)
    merged = merge_fingerprints(names, args.name)
    path = save_fingerprint(args.name, merged)
    print(f"✓ 已合并 {len(names)} 份指纹 → {path}")
    print_report(args.name, merged)


def cmd_export(args):
    fp = load_fingerprint(args.name)
    guide = export_guide(fp)
    if args.output:
        Path(args.output).write_text(guide, encoding="utf-8")
        print(f"✓ 指南已导出: {args.output}")
    else:
        print(guide)


def cmd_list(args):
    files = list_fingerprints()
    if not files:
        print("（暂无指纹。用 analyze 创建。）")
        return
    print()
    print(f"{'名称':<20} {'字数':>6} {'句数':>5} {'置信':>4}  创建时间")
    print("─" * 62)
    for f in files:
        try:
            fp = json.loads(f.read_text(encoding="utf-8"))
            s = fp.get("sample", {})
            conf = "低" if s.get("low_confidence") else "高"
            print(f"{fp.get('name', f.stem):<20} {s.get('char_count', 0):>6} "
                  f"{s.get('sentence_count', 0):>5} {conf:>4}  "
                  f"{fp.get('created_at', '?')}")
        except Exception as e:
            print(f"{f.stem:<20} （读取失败: {e}）")
    print()


def cmd_show(args):
    fp = load_fingerprint(args.name)
    print(json.dumps(fp, ensure_ascii=False, indent=2))


def cmd_delete(args):
    if delete_fingerprint(args.name):
        print(f"✓ 已删除: {args.name}")
    else:
        print(f"❌ 指纹不存在: {args.name}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Style Fingerprint v2 - 中文写作风格指纹（零依赖）")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("analyze", help="分析文本/文件并保存指纹")
    p.add_argument("--text")
    p.add_argument("--file")
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("compare", help="新文本 vs 指纹，风格偏差校验")
    p.add_argument("--name", required=True, help="已保存的指纹名")
    p.add_argument("--text")
    p.add_argument("--file")
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("merge", help="合并多个指纹（按字数加权）")
    p.add_argument("--names", required=True, help="逗号分隔，如 a,b,c")
    p.add_argument("--name", required=True, help="合并后指纹名")
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("list", help="列出所有指纹")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="查看指纹 JSON")
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("delete", help="删除指纹")
    p.add_argument("--name", required=True)
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("export", help="导出写作指南（规则+范例）")
    p.add_argument("--name", required=True)
    p.add_argument("--output")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("selftest", help="内置回归测试")
    p.set_defaults(func=lambda a: sys.exit(0 if selftest() else 1))

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
