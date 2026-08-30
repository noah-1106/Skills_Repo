---
name: style-fingerprint
description: |
  Analyze and save Chinese writing style fingerprints (v2, zero dependencies).
  Extracts rhythm, function-word habits, rhetoric patterns and exemplar sentences.
  NEW in v2: compare (draft vs fingerprint deviation report), merge (multi-text),
  selftest (regression), exemplar few-shot export, low-confidence marking.
  
  分析并保存中文写作风格指纹（v2，零依赖）。
  提取节奏、功能词习惯、句式修辞与范例句。
  v2 新增：compare 新稿校验、merge 多文本合并、selftest 回归测试、
  范例句导出（few-shot）、小样本置信度标注。
metadata:
  openclaw:
    requires:
      bins: ["python3"]
    emoji: \U0001F3A8
    category: writing
commands:
  - name: analyze
    description: Analyze text/file and save fingerprint | 分析文本/文件并保存指纹
    args:
      - {name: text, flag: "--text", required: false, description: "Text to analyze | 要分析的文本"}
      - {name: file, flag: "--file", required: false, description: "File to analyze | 要分析的文件"}
      - {name: name, flag: "--name", required: true, description: "Fingerprint name | 指纹名称"}
  - name: list
    description: List all fingerprints | 列出所有指纹
  - name: show
    description: Show fingerprint details | 显示指纹详情
    args:
      - {name: name, flag: "--name", required: true}
  - name: delete
    description: Delete a fingerprint | 删除指纹
    args:
      - {name: name, flag: "--name", required: true}
  - name: export
    description: Export style guide (rules + exemplar sentences) | 导出风格指南（规则+范例句）
    args:
      - {name: name, flag: "--name", required: true}
      - {name: output, flag: "--output", required: false, description: "Output file | 输出文件"}
  - name: compare
    description: Check a draft against a fingerprint (deviation report) | 新稿 vs 指纹偏差校验
    args:
      - {name: name, flag: "--name", required: true, description: "Fingerprint to compare against | 指纹名"}
      - {name: text, flag: "--text", required: false}
      - {name: file, flag: "--file", required: false}
  - name: merge
    description: Merge multiple fingerprints (weighted by char count) | 合并多个指纹（按字数加权）
    args:
      - {name: names, flag: "--names", required: true, description: "Comma-separated names | 逗号分隔"}
      - {name: name, flag: "--name", required: true, description: "Merged fingerprint name | 合并后名称"}
  - name: selftest
    description: Run built-in regression tests | 运行内置回归测试
---

# Style Fingerprint v2 | 写作风格指纹

## What changed in v2 | v2 变更

| Fix/New | 说明 |
|---|---|
| Fixed | 反问句检测（v1 正则语序错误，永远返回 0） |
| Fixed | 被动语态误伤「由于/自由」 |
| Fixed | 省略主语字符类拆词误判 |
| Fixed | 隐喻误报（排除副词「好像/似乎」） |
| Rewritten | 词汇层：滑窗伪分词 → 封闭集合功能词指纹（疑问/连接/情态/程度/人称/语气词）+ 跨句口头禅候选 |
| New | `compare`：新稿 vs 指纹，15 维度偏差报告 + 修正建议（写作质量闸门） |
| New | `merge`：多文本合并指纹（按字数加权） |
| New | `export` 范例句层：few-shot 例句比规则对 LLM 更有效 |
| New | `selftest`：11 项内置回归用例 |
| New | <300 字自动标注低置信度 |
| Format | 指纹 JSON v2：全部指标改为比率（每百句/每千字），跨文本可比 |

## Recommended workflow | 推荐工作流

```bash
# 1. 提取作者指纹（建议 ≥300 字，多篇可用 merge 合并）
python3 style_fingerprint.py analyze --file author_a_1.txt --name 作者A
python3 style_fingerprint.py analyze --file author_a_2.txt --name 作者A2
python3 style_fingerprint.py merge --names "作者A,作者A2" --name 作者A综合

# 2. 导出风格指南（规则 + 范例句）给写作 Agent
python3 style_fingerprint.py export --name 作者A综合 --output style_guide.md

# 3. Agent 写作后，校验新稿是否还原了风格
python3 style_fingerprint.py compare --name 作者A综合 --file draft.txt
```

## Notes | 注意

- 指纹保存在技能目录 `fingerprints/` 下（自包含设计，拷贝技能即带走数据）
- <300 字的样本会标注 low_confidence，结论仅供参考
- compare 一致率是参考值：句式类维度 ±30% 内为 ✅
- 零外部依赖，Python 3.7+ 即可运行
