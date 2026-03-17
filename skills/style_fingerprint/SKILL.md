---
name: style-fingerprint
description: |
  Analyze and save Chinese writing style fingerprints. 
  Extracts syntax patterns, lexical preferences, rhetorical features from text.
  Saves fingerprints to ./fingerprints/ for writing agents to use.
  No external dependencies - pure Python implementation.
  
  分析和保存中文写作风格指纹。从文本中提取句法模式、词汇偏好、修辞特征。
  将指纹保存到 ./fingerprints/ 目录供写作助手使用。
  无外部依赖 - 纯 Python 实现。
metadata:
  openclaw:
    requires:
      bins: ["python3"]
    emoji: 🎨
    category: writing
commands:
  - name: analyze
    description: Analyze text/file and save fingerprint | 分析文本/文件并保存指纹
    args:
      - name: text
        flag: --text
        required: false
        description: Text content to analyze | 要分析的文本内容
      - name: file
        flag: --file
        required: false
        description: File path to analyze | 要分析的文件路径
      - name: name
        flag: --name
        required: true
        description: Fingerprint name (for saving) | 指纹名称（用于保存）
  
  - name: list
    description: List all saved fingerprints | 列出所有保存的指纹
  
  - name: show
    description: Show fingerprint details | 显示指纹详情
    args:
      - name: name
        flag: --name
        required: true
  
  - name: delete
    description: Delete a fingerprint | 删除指纹
    args:
      - name: name
        flag: --name
        required: true
  
  - name: export
    description: Export style guide for writing agent | 导出写作助手指南
    args:
      - name: name
        flag: --name
        required: true
      - name: output
        flag: --output
        required: false
        description: Output file path | 输出文件路径
---

# Style Fingerprint | 写作风格指纹

**English**: Analyze Chinese writing style and save fingerprints for AI writing agents.

**中文**: 分析中文写作风格并保存指纹，供 AI 写作助手使用。

---

## Quick Start | 快速开始

```bash
# Analyze text | 分析文本
python3 style_fingerprint.py analyze --text "你的文本内容" --name "我的风格"

# Analyze file | 分析文件
python3 style_fingerprint.py analyze --file ./article.txt --name "作者A"

# List saved fingerprints | 列出保存的指纹
python3 style_fingerprint.py list

# Show fingerprint details | 显示指纹详情
python3 style_fingerprint.py show --name "我的风格"

# Export style guide for writing agent | 导出写作助手指南
python3 style_fingerprint.py export --name "我的风格" --output ./guide.txt
```

---

## What It Analyzes | 分析维度

**English**:
- **Basic Stats**: Sentence length, rhythm, comma density
- **Syntax Patterns**: Rhetorical questions, passive voice, ellipsis
- **Lexical Fingerprint**: Top words, word diversity
- **Logic Flow**: Transition word preferences
- **Rhetoric**: Metaphors, sensory description types

**中文**:
- **基础统计**: 句子长度、节奏感、逗号密度
- **句法模式**: 修辞问句、被动语态、省略号使用
- **词汇指纹**: 高频词汇、词汇多样性
- **逻辑流**: 过渡词偏好
- **修辞手法**: 隐喻、感官描述类型

---

## Storage | 存储

**English**: Fingerprints are saved in `./fingerprints/` as JSON files.

**中文**: 指纹以 JSON 格式保存在 `./fingerprints/` 目录中。

---

## For Writing Agents | 供写作助手使用

**English**: Use `export` command to get a compact style guide that can be included in prompts.

**中文**: 使用 `export` 命令获取紧凑的风格指南，可嵌入到提示词中使用。

---

## Features | 特性

**English**:
- ✅ **No external dependencies** - Pure Python implementation
- ✅ **Chinese optimized** - Designed for Chinese text analysis
- ✅ **Persistent storage** - Saves fingerprints to `./fingerprints/`
- ✅ **Writing agent ready** - Export compact style guides

**中文**:
- ✅ **无外部依赖** - 纯 Python 实现
- ✅ **中文优化** - 专为中文文本分析设计
- ✅ **持久化存储** - 将指纹保存到 `./fingerprints/`
- ✅ **写作助手就绪** - 导出紧凑的风格指南
